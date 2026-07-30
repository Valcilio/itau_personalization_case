"""Entrypoint for the model training pipeline."""

import json
import os
import shutil
import sys
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from model_train.domain.gateways.awsconnector import AwsConnector
from model_train.domain.gateways.modelhandler import ModelHandler
from model_train.domain.utils.modeltrainerlogger import ModelTrainerLogger


@dataclass(frozen=True)
class PipelineResult:
    """Summary returned after a full training pipeline execution."""

    model_version: str
    model_output_dir: str
    model_s3_uri: str
    model_package_arn: str
    baseline_model_package_arn: str | None
    accuracy: str
    roc_auc: str
    validated_customers: int


logger = ModelTrainerLogger("main")


def load_config() -> dict[str, str]:
    """Load runtime configuration from environment variables.

    Returns:
        Dictionary with local paths, AWS settings and model versioning data.

    Raises:
        ValueError: If ``IMAGE_TAG`` is not configured.
    """
    image_tag = os.getenv("IMAGE_TAG", "").strip()
    if not image_tag:
        raise ValueError(
            "IMAGE_TAG is required and must match the Docker image tag used as model version"
        )

    return {
        "data_bucket": os.getenv("DATA_BUCKET", ""),
        "data_prefix": os.getenv("DATA_PREFIX", "training-data"),
        "model_bucket": os.getenv("MODEL_BUCKET", ""),
        "model_prefix": os.getenv(
            "MODEL_PREFIX",
            f"models/purchase_propensity/{image_tag}",
        ),
        "model_output_dir": os.getenv(
            "MODEL_OUTPUT_DIR",
            os.getenv("SM_MODEL_DIR", "/tmp/model"),
        ),
        "training_data_dir": os.getenv(
            "TRAINING_DATA_DIR",
            os.getenv("SM_CHANNEL_TRAINING", "/tmp/training"),
        ),
        "model_package_group_name": os.getenv(
            "MODEL_PACKAGE_GROUP_NAME",
            "purchase-propensity-model-group",
        ),
        "inference_image_uri": os.getenv("INFERENCE_IMAGE_URI", ""),
        "model_version": image_tag,
        "baseline_model_dir": os.getenv("BASELINE_MODEL_DIR", "").strip(),
        "baseline_model_prefix": os.getenv(
            "BASELINE_MODEL_PREFIX",
            "models/purchase_propensity/case-baseline-v1",
        ),
    }


def load_datasets(
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load training datasets from S3.

    Args:
        config: Pipeline configuration produced by ``load_config``.
        aws_connector: AWS gateway used to download training CSVs.

    Returns:
        Events and products dataframes ready for feature engineering.

    Raises:
        ValueError: If ``DATA_BUCKET`` is not configured.
    """
    if not config["data_bucket"]:
        raise ValueError("DATA_BUCKET is required to load training datasets from S3")

    logger.info(
        "dataset_source_selected",
        source="s3",
        bucket=config["data_bucket"],
        prefix=config["data_prefix"],
    )
    dataset_paths = aws_connector.download_training_dataset(
        bucket=config["data_bucket"],
        prefix=config["data_prefix"],
        local_dir=config["training_data_dir"],
    )
    events_path = dataset_paths["events"]
    products_path = dataset_paths["products"]

    events = pd.read_csv(events_path)
    products = pd.read_csv(products_path)
    logger.info(
        "datasets_loaded",
        events_rows=len(events),
        products_rows=len(products),
        events_path=str(events_path),
        products_path=str(products_path),
    )
    return events, products


def resolve_baseline_model_dir(config: dict[str, str]) -> Path:
    """Resolve the directory containing the case baseline ``model.pkl``."""
    if config["baseline_model_dir"]:
        return Path(config["baseline_model_dir"])

    for candidate in (
        Path("/app/model"),
        Path(__file__).resolve().parents[2] / "model",
    ):
        if (candidate / "model.pkl").exists() or (candidate / "model.tar.gz").exists():
            return candidate

    return Path("/app/model")


def prepare_baseline_model_dir(source_dir: Path, work_dir: Path) -> Path:
    """Return a directory with ``model.pkl`` ready to upload to SageMaker."""
    if (source_dir / "model.pkl").exists():
        return source_dir

    archive_path = source_dir / "model.tar.gz"
    if not archive_path.exists():
        raise FileNotFoundError(
            "Baseline model not found. Expected model.pkl or model.tar.gz in "
            f"{source_dir}"
        )

    extract_dir = work_dir / "baseline-model"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as archive:
        extract_kwargs: dict[str, str] = {}
        if hasattr(tarfile, "data_filter"):
            extract_kwargs["filter"] = "data"
        archive.extractall(extract_dir, **extract_kwargs)

    if not (extract_dir / "model.pkl").exists():
        raise FileNotFoundError(
            f"Baseline archive {archive_path} does not contain model.pkl"
        )

    model_card_source = source_dir / "model_card.json"
    if model_card_source.exists() and not (extract_dir / "model_card.json").exists():
        shutil.copy2(model_card_source, extract_dir / "model_card.json")

    return extract_dir


def seed_baseline_model_if_needed(
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> str | None:
    """Register the bundled case model as version 1 when the registry is empty."""
    if not config["model_bucket"] or not config["inference_image_uri"]:
        logger.warning(
            "baseline_model_seed_skipped",
            reason="model_bucket_or_inference_image_not_configured",
        )
        return None

    if aws_connector.has_model_packages(config["model_package_group_name"]):
        logger.info(
            "baseline_model_seed_skipped",
            reason="model_registry_not_empty",
            model_package_group_name=config["model_package_group_name"],
        )
        return None

    source_dir = resolve_baseline_model_dir(config)
    staging_dir = prepare_baseline_model_dir(
        source_dir,
        Path(config["model_output_dir"]).parent / "baseline-model-staging",
    )
    logger.info(
        "baseline_model_seed_started",
        source_dir=str(source_dir),
        staging_dir=str(staging_dir),
        model_package_group_name=config["model_package_group_name"],
    )

    model_s3_uri = aws_connector.upload_model_directory(
        local_dir=staging_dir,
        bucket=config["model_bucket"],
        prefix=config["baseline_model_prefix"],
    )
    baseline_arn = aws_connector.register_model_package(
        model_package_group_name=config["model_package_group_name"],
        model_data_url=model_s3_uri,
        image_uri=config["inference_image_uri"],
        model_name="purchase_propensity_v1",
        description=(
            "Baseline purchase propensity model shipped with the case "
            "(model/model.pkl), registered as version 1."
        ),
    )
    logger.info(
        "baseline_model_seed_completed",
        baseline_model_package_arn=baseline_arn,
        model_s3_uri=model_s3_uri,
    )
    return baseline_arn


def publish_model_artifact(
    output_dir: Path,
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> str:
    """Publish local model artifacts to S3 when configured.

    Args:
        output_dir: Directory containing ``model.pkl`` and ``model_card.json``.
        config: Pipeline configuration produced by ``load_config``.
        aws_connector: AWS gateway responsible for uploading files.

    Returns:
        Local or remote URI pointing to the primary model artifact.
    """
    if not config["model_bucket"]:
        logger.warning(
            "model_publish_skipped",
            reason="model_bucket_not_configured",
            local_artifact=str(output_dir / "model.pkl"),
        )
        return str(output_dir / "model.pkl")

    return aws_connector.upload_model_directory(
        local_dir=output_dir,
        bucket=config["model_bucket"],
        prefix=config["model_prefix"],
    )


def register_model_version(
    model_s3_uri: str,
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> str:
    """Register the trained model in SageMaker Model Registry when configured.

    Args:
        model_s3_uri: S3 URI of the uploaded model artifact.
        config: Pipeline configuration produced by ``load_config``.
        aws_connector: AWS gateway responsible for registry operations.

    Returns:
        Model package ARN when registration succeeds, otherwise an empty string.
    """
    if not config["model_bucket"] or not config["inference_image_uri"]:
        logger.warning(
            "model_registry_registration_skipped",
            reason="model_bucket_or_inference_image_not_configured",
        )
        return ""

    return aws_connector.register_model_package(
        model_package_group_name=config["model_package_group_name"],
        model_data_url=model_s3_uri,
        image_uri=config["inference_image_uri"],
        model_name=f"purchase_propensity_{config['model_version']}",
        description=(
            f"Purchase propensity model version {config['model_version']} "
            "generated by ECS training task."
        ),
    )


def run_training_pipeline() -> PipelineResult:
    """Execute the full training pipeline end to end.

    Returns:
        Summary with metrics, local paths and AWS registration details.
    """
    config = load_config()
    logger.info(
        "training_pipeline_started",
        model_version=config["model_version"],
        model_output_dir=config["model_output_dir"],
    )

    aws_connector = AwsConnector()
    model_handler = ModelHandler()

    baseline_model_package_arn = seed_baseline_model_if_needed(config, aws_connector)

    events, products = load_datasets(config, aws_connector)
    output_dir = Path(config["model_output_dir"])
    handler_result = model_handler.train_and_persist(
        events,
        products,
        output_dir,
        config["model_version"],
    )

    model_s3_uri = publish_model_artifact(output_dir, config, aws_connector)
    model_package_arn = register_model_version(model_s3_uri, config, aws_connector)

    training_result = handler_result.training_result
    result = PipelineResult(
        model_version=config["model_version"],
        model_output_dir=str(output_dir),
        model_s3_uri=model_s3_uri,
        model_package_arn=model_package_arn,
        baseline_model_package_arn=baseline_model_package_arn,
        accuracy=str(training_result.metrics["accuracy"]),
        roc_auc=str(training_result.metrics["roc_auc"]),
        validated_customers=training_result.validated_customers,
    )
    logger.info(
        "training_pipeline_completed",
        model_version=result.model_version,
        model_s3_uri=result.model_s3_uri,
        model_package_arn=result.model_package_arn,
        baseline_model_package_arn=result.baseline_model_package_arn,
        accuracy=result.accuracy,
        roc_auc=result.roc_auc,
        validated_customers=result.validated_customers,
    )
    return result


def main() -> int:
    """Configure logging and run the model training pipeline."""
    ModelTrainerLogger.configure()

    try:
        result = run_training_pipeline()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("training_pipeline_failed")
        return 1

    print(json.dumps(asdict(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
