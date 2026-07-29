"""Gateway responsible for feature engineering and model artifact handling."""

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from model_train.domain.usecases.modeltrainer import ModelTrainer, TrainingResult
from model_train.domain.utils.modeltrainerlogger import ModelTrainerLogger


@dataclass(frozen=True)
class HandlerResult:
    """Artifacts and metrics produced by ``ModelHandler.train_and_persist``."""

    training_result: TrainingResult
    artifact_path: Path
    model_card_path: Path


class ModelHandler:
    """Prepare training data, invoke training and persist model artifacts.

    ``ModelHandler`` owns feature engineering and local artifact serialization.
    It delegates model fitting to ``ModelTrainer`` and does not talk to AWS
    directly. External orchestration is responsible for publishing artifacts.
    """

    FEATURE_COLUMNS = [
        "interactions",
        "price",
        "avg_rating",
        "popularity_score",
        "user_affinity_match",
    ]

    PURCHASE_EVENT = "purchase"

    def __init__(self, model_trainer: ModelTrainer | None = None) -> None:
        """Initialize the handler.

        Args:
            model_trainer: Optional trainer instance, useful for testing.
        """
        self.model_trainer = model_trainer or ModelTrainer()
        self.logger = ModelTrainerLogger(self.__class__.__name__)

    def train_and_persist(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
        output_dir: str | Path,
        version: str,
    ) -> HandlerResult:
        """Build features, train the model and persist local artifacts.

        Args:
            events: Raw user interaction events.
            products: Product catalog used to derive product-level features.
            output_dir: Directory where ``model.pkl`` and ``model_card.json`` are saved.
            version: Model version written to the model card.

        Returns:
            Training metrics plus local paths for the generated artifacts.
        """
        self.logger.info(
            "training_pipeline_stage_started",
            stage="train_and_persist",
            events_rows=len(events),
            products_rows=len(products),
            output_dir=str(output_dir),
            version=version,
        )

        features, labels = self.build_training_dataset(events, products)
        self.logger.info(
            "training_dataset_built",
            feature_rows=len(features),
            positive_labels=int(labels.sum()),
        )

        training_result = self.model_trainer.train(features, labels)
        artifact = self.create_artifact(training_result.model, training_result.scaler)
        artifact_path = self.save_artifact(artifact, output_dir)
        model_card_path = self.save_model_card(
            output_dir,
            training_result.metrics,
            version,
        )

        self.logger.info(
            "training_pipeline_stage_completed",
            stage="train_and_persist",
            artifact_path=str(artifact_path),
            model_card_path=str(model_card_path),
            accuracy=training_result.metrics["accuracy"],
            roc_auc=training_result.metrics["roc_auc"],
        )

        return HandlerResult(
            training_result=training_result,
            artifact_path=artifact_path,
            model_card_path=model_card_path,
        )

    def build_training_dataset(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Build the supervised dataset used for model training.

        Args:
            events: Historical user-product interactions.
            products: Product metadata used to enrich each training row.

        Returns:
            Feature matrix and binary purchase labels.
        """
        pairs = events[["user_id", "product_id"]].drop_duplicates()
        features = self._build_features(events, products, pairs)
        labels = self._build_labels(events, pairs)
        return features, labels

    def create_artifact(
        self,
        model: LogisticRegression,
        scaler: StandardScaler,
    ) -> dict[str, object]:
        """Build the serialized artifact expected by downstream services.

        Args:
            model: Trained classifier.
            scaler: Fitted feature scaler.

        Returns:
            Dictionary ready to be pickled and served in production.
        """
        return {
            "model": model,
            "scaler": scaler,
            "feature_cols": self.FEATURE_COLUMNS,
        }

    def save_artifact(self, artifact: dict[str, object], output_dir: str | Path) -> Path:
        """Persist the model artifact to disk.

        Args:
            artifact: Object returned by ``create_artifact``.
            output_dir: Destination directory for ``model.pkl``.

        Returns:
            Path to the saved pickle file.
        """
        output_directory = Path(output_dir)
        output_directory.mkdir(parents=True, exist_ok=True)
        artifact_path = output_directory / "model.pkl"
        with artifact_path.open("wb") as artifact_file:
            pickle.dump(artifact, artifact_file)
        self.logger.info("model_artifact_saved", artifact_path=str(artifact_path))
        return artifact_path

    def save_model_card(
        self,
        output_dir: str | Path,
        metrics: dict[str, float],
        version: str,
    ) -> Path:
        """Persist the model card describing the trained artifact.

        Args:
            output_dir: Destination directory for ``model_card.json``.
            metrics: Offline evaluation metrics produced during training.
            version: Model version string.

        Returns:
            Path to the saved model card.
        """
        output_directory = Path(output_dir)
        output_directory.mkdir(parents=True, exist_ok=True)
        model_card = {
            "model_name": "purchase_propensity_v1",
            "model_type": "sklearn.linear_model.LogisticRegression",
            "version": version,
            "input_features": self.FEATURE_COLUMNS,
            "feature_descriptions": {
                "interactions": (
                    "numero de interacoes do usuario com o produto (historico)"
                ),
                "price": "preco do produto (products.csv)",
                "avg_rating": "avaliacao media do produto (products.csv)",
                "popularity_score": (
                    "score de popularidade global do produto, 0-1 (products.csv)"
                ),
                "user_affinity_match": (
                    "1 se a categoria do produto bate com a categoria de maior "
                    "afinidade historica do usuario, senao 0"
                ),
            },
            "output": (
                "probabilidade de compra (score entre 0 e 1), "
                "usado para ranquear produtos"
            ),
            "training_metrics": metrics,
            "notes": (
                "Modelo gerado pelo job de treino do SageMaker pipeline. "
                "Registrado no SageMaker Model Registry como latest."
            ),
        }
        model_card_path = output_directory / "model_card.json"
        with model_card_path.open("w", encoding="utf-8") as model_card_file:
            json.dump(model_card, model_card_file, indent=2, ensure_ascii=False)
        self.logger.info("model_card_saved", model_card_path=str(model_card_path), version=version)
        return model_card_path

    def _build_labels(self, events: pd.DataFrame, pairs: pd.DataFrame) -> pd.Series:
        """Create binary purchase labels for each user-product pair."""
        purchase_pairs = (
            events.loc[events["event_type"] == self.PURCHASE_EVENT, ["user_id", "product_id"]]
            .drop_duplicates()
            .assign(purchased=1)
        )
        labeled_pairs = pairs.merge(
            purchase_pairs,
            on=["user_id", "product_id"],
            how="left",
        )
        return labeled_pairs["purchased"].fillna(0).astype(int)

    def _build_features(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
        pairs: pd.DataFrame,
    ) -> pd.DataFrame:
        """Derive model features for each user-product pair."""
        interactions = (
            events.groupby(["user_id", "product_id"], as_index=False)
            .size()
            .rename(columns={"size": "interactions"})
        )
        product_features = products[
            ["product_id", "category", "price", "avg_rating", "popularity_score"]
        ]
        top_affinity = self._compute_user_top_affinity_category(events, products)

        features = (
            pairs.merge(interactions, on=["user_id", "product_id"], how="left")
            .merge(product_features, on="product_id", how="left")
            .merge(top_affinity, on="user_id", how="left")
        )

        features["interactions"] = features["interactions"].fillna(0).astype(int)
        features["user_affinity_match"] = (
            features["category"] == features["top_affinity_category"]
        ).astype(int)

        return features[["user_id", "product_id", *self.FEATURE_COLUMNS]]

    def _compute_user_top_affinity_category(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute each user's top affinity category from historical events."""
        events_with_category = events.merge(
            products[["product_id", "category"]],
            on="product_id",
            how="inner",
        )
        category_counts = (
            events_with_category.groupby(["user_id", "category"], as_index=False)
            .size()
            .rename(columns={"size": "interaction_count"})
        )
        return (
            category_counts.sort_values(
                ["user_id", "interaction_count", "category"],
                ascending=[True, False, True],
            )
            .drop_duplicates("user_id")
            .rename(columns={"category": "top_affinity_category"})[
                ["user_id", "top_affinity_category"]
            ]
        )
