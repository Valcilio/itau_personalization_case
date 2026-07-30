#!/usr/bin/env bash
# Reconcile Terraform state with AWS resources left behind after a partial destroy
# or when the remote state was reset. Safe to re-run: skips addresses already imported.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${TF_DIR}"

PROJECT_NAME="${PROJECT_NAME:-personalization}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_TAG="${IMAGE_TAG:-UAT}"
export AWS_REGION
TF_VARS=(-var="image_tag=${IMAGE_TAG}" -var="aws_region=${AWS_REGION}")

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
DATA_BUCKET="${PROJECT_NAME}-data-${ACCOUNT_ID}"
MODELS_BUCKET="${PROJECT_NAME}-models-${ACCOUNT_ID}"

echo "Reconciling Terraform state for account ${ACCOUNT_ID} in ${AWS_REGION}..."

terraform init -input=false

import_if_missing() {
  local address="$1"
  local resource_id="$2"

  if terraform state show "${address}" >/dev/null 2>&1; then
    echo "SKIP (already in state): ${address}"
    return 0
  fi

  echo "IMPORT: ${address} <= ${resource_id}"
  terraform import -input=false "${TF_VARS[@]}" "${address}" "${resource_id}"
}

sg_id() {
  aws ec2 describe-security-groups \
    --region "${AWS_REGION}" \
    --filters "Name=group-name,Values=$1" "Name=vpc-id,Values=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text --region "${AWS_REGION}")" \
    --query 'SecurityGroups[0].GroupId' \
    --output text
}

lb_arn() {
  aws elbv2 describe-load-balancers \
    --region "${AWS_REGION}" \
    --names "$1" \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text 2>/dev/null || true
}

tg_arn() {
  aws elbv2 describe-target-groups \
    --region "${AWS_REGION}" \
    --names "$1" \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text 2>/dev/null || true
}

sns_topic_arn() {
  aws sns list-topics \
    --region "${AWS_REGION}" \
    --query "Topics[?contains(TopicArn, ':${1}\$')].TopicArn | [0]" \
    --output text 2>/dev/null || true
}

# --- ECR repositories (import first; other resources depend on image URIs) ---
for repo_key in model_train model_predict recommendations_api model_drift_monitor; do
  case "${repo_key}" in
    model_train) repo_name="${PROJECT_NAME}-model-train" ;;
    model_predict) repo_name="${PROJECT_NAME}-model-predict" ;;
    recommendations_api) repo_name="${PROJECT_NAME}-recommendations-api" ;;
    model_drift_monitor) repo_name="${PROJECT_NAME}-model-drift-monitor" ;;
  esac
  import_if_missing "aws_ecr_repository.services[\"${repo_key}\"]" "${repo_name}"
done

# --- Core storage ---
import_if_missing "aws_s3_bucket.data" "${DATA_BUCKET}"
import_if_missing "aws_s3_bucket.models" "${MODELS_BUCKET}"
import_if_missing "aws_s3_bucket_public_access_block.data" "${DATA_BUCKET}"
import_if_missing "aws_s3_bucket_public_access_block.models" "${MODELS_BUCKET}"
import_if_missing "aws_s3_bucket_policy.models_sagemaker_read" "${MODELS_BUCKET}"

# --- DynamoDB ---
import_if_missing "aws_dynamodb_table.predictions" "${PROJECT_NAME}-predictions"
import_if_missing "aws_dynamodb_table.integration_predictions" "${PROJECT_NAME}-integration-predictions"

# --- CloudWatch log groups ---
import_if_missing "aws_cloudwatch_log_group.model_train" "/ecs/${PROJECT_NAME}/model-train"
import_if_missing "aws_cloudwatch_log_group.model_predict" "/ecs/${PROJECT_NAME}/model-predict"
import_if_missing "aws_cloudwatch_log_group.recommendations_api" "/ecs/${PROJECT_NAME}/recommendations-api"
import_if_missing "aws_cloudwatch_log_group.model_drift_monitor" "/ecs/${PROJECT_NAME}/model-drift-monitor"

# --- ECR policies (after repositories) ---
for repo_key in model_train model_predict recommendations_api model_drift_monitor; do
  case "${repo_key}" in
    model_train) repo_name="${PROJECT_NAME}-model-train" ;;
    model_predict) repo_name="${PROJECT_NAME}-model-predict" ;;
    recommendations_api) repo_name="${PROJECT_NAME}-recommendations-api" ;;
    model_drift_monitor) repo_name="${PROJECT_NAME}-model-drift-monitor" ;;
  esac
  import_if_missing "aws_ecr_repository_policy.sagemaker_pull[\"${repo_key}\"]" "${repo_name}"
  import_if_missing "aws_ecr_lifecycle_policy.services[\"${repo_key}\"]" "${repo_name}"
done

# --- IAM ---
import_if_missing "aws_iam_role.ecs_task_execution" "${PROJECT_NAME}-ecs-task-execution"
import_if_missing "aws_iam_role.ecs_task" "${PROJECT_NAME}-ecs-task"
import_if_missing "aws_iam_role_policy_attachment.ecs_task_execution" \
  "${PROJECT_NAME}-ecs-task-execution/arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
import_if_missing "aws_iam_role_policy.ecs_task" "${PROJECT_NAME}-ecs-task:${PROJECT_NAME}-ecs-task"

# --- SageMaker Model Registry ---
import_if_missing "aws_sagemaker_model_package_group.purchase_propensity" "purchase-propensity-model-group"
import_if_missing "aws_sagemaker_model_package_group.integration" "${PROJECT_NAME}-integration-model-group"

# --- Security groups ---
for sg_name in \
  "${PROJECT_NAME}-model-train-ecs" \
  "${PROJECT_NAME}-model-predict-ecs" \
  "${PROJECT_NAME}-model-drift-monitor-ecs" \
  "${PROJECT_NAME}-recommendations-alb" \
  "${PROJECT_NAME}-recommendations-api-ecs"; do
  sg="$(sg_id "${sg_name}")"
  if [[ "${sg}" != "None" && -n "${sg}" ]]; then
    case "${sg_name}" in
      *model-train*) import_if_missing "aws_security_group.model_train" "${sg}" ;;
      *model-predict*) import_if_missing "aws_security_group.model_predict" "${sg}" ;;
      *model-drift-monitor*) import_if_missing "aws_security_group.model_drift_monitor" "${sg}" ;;
      *recommendations-alb*) import_if_missing "aws_security_group.recommendations_alb" "${sg}" ;;
      *recommendations-api-ecs*) import_if_missing "aws_security_group.recommendations_api" "${sg}" ;;
    esac
  fi
done

# --- ECS clusters ---
import_if_missing "aws_ecs_cluster.model_train" "${PROJECT_NAME}-model-train"
import_if_missing "aws_ecs_cluster.model_predict" "${PROJECT_NAME}-model-predict"
import_if_missing "aws_ecs_cluster.model_drift_monitor" "${PROJECT_NAME}-model-drift-monitor"
import_if_missing "aws_ecs_cluster.recommendations_api" "${PROJECT_NAME}-recommendations-api"

# --- Load balancers / target groups ---
ALB_ARN="$(lb_arn "${PROJECT_NAME}-recs-alb")"
NLB_ARN="$(lb_arn "${PROJECT_NAME}-recs-nlb")"
TG_ARN="$(tg_arn "${PROJECT_NAME}-recs-tg")"
NLB_TG_ARN="$(tg_arn "${PROJECT_NAME}-recs-nlb-alb")"

if [[ -n "${ALB_ARN}" && "${ALB_ARN}" != "None" ]]; then
  import_if_missing "aws_lb.recommendations" "${ALB_ARN}"
fi
if [[ -n "${NLB_ARN}" && "${NLB_ARN}" != "None" ]]; then
  import_if_missing "aws_lb.recommendations_nlb" "${NLB_ARN}"
fi
if [[ -n "${TG_ARN}" && "${TG_ARN}" != "None" ]]; then
  import_if_missing "aws_lb_target_group.recommendations" "${TG_ARN}"
fi
if [[ -n "${NLB_TG_ARN}" && "${NLB_TG_ARN}" != "None" ]]; then
  import_if_missing "aws_lb_target_group.recommendations_nlb_alb" "${NLB_TG_ARN}"
fi

# --- SNS ---
DRIFT_TOPIC_ARN="$(sns_topic_arn "${PROJECT_NAME}-model-drift-alerts")"
if [[ -n "${DRIFT_TOPIC_ARN}" && "${DRIFT_TOPIC_ARN}" != "None" ]]; then
  import_if_missing "aws_sns_topic.model_drift_alerts" "${DRIFT_TOPIC_ARN}"
fi

# --- SSM parameter (import by name; apply will refresh value with overwrite=true) ---
import_if_missing "aws_ssm_parameter.recommendations_api_key" "/${PROJECT_NAME}/recommendations-api/api-key"

echo ""
echo "Refreshing Terraform state..."
terraform refresh "${TF_VARS[@]}"

echo ""
echo "Import pass completed."
echo "Next: terraform plan -var=\"image_tag=<tag>\" and review remaining creates/updates."
echo "Some resources (API Gateway, ECS services, listeners) may still need manual import if they exist."
