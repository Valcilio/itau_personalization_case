#!/usr/bin/env bash
# Fast reset: delete personalization AWS resources and clear Terraform state.
# Preserves bootstrap (terraform state bucket + lock table). Much faster than importing orphans.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${TF_DIR}"

PROJECT_NAME="${PROJECT_NAME:-personalization}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_TAG="${IMAGE_TAG:-UAT}"
export AWS_REGION

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
DATA_BUCKET="${PROJECT_NAME}-data-${ACCOUNT_ID}"
MODELS_BUCKET="${PROJECT_NAME}-models-${ACCOUNT_ID}"

echo "=== Fast reset for ${PROJECT_NAME} (account ${ACCOUNT_ID}, region ${AWS_REGION}) ==="

terraform init -input=false

echo "--- Stopping ECS services ---"
for cluster in \
  "${PROJECT_NAME}-recommendations-api" \
  "${PROJECT_NAME}-model-train" \
  "${PROJECT_NAME}-model-predict" \
  "${PROJECT_NAME}-model-drift-monitor"; do
  aws ecs update-service \
    --cluster "${cluster}" \
    --service "${cluster}" \
    --desired-count 0 \
    --region "${AWS_REGION}" 2>/dev/null || true
done

echo "--- Deleting ECS services ---"
aws ecs delete-service --cluster "${PROJECT_NAME}-recommendations-api" \
  --service "${PROJECT_NAME}-recommendations-api" --force --region "${AWS_REGION}" 2>/dev/null || true

echo "--- Deleting load balancers ---"
for lb in "${PROJECT_NAME}-recs-alb" "${PROJECT_NAME}-recs-nlb"; do
  arn="$(aws elbv2 describe-load-balancers --names "${lb}" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text --region "${AWS_REGION}" 2>/dev/null || true)"
  if [[ -n "${arn}" && "${arn}" != "None" ]]; then
    aws elbv2 delete-load-balancer --load-balancer-arn "${arn}" --region "${AWS_REGION}" || true
  fi
done

echo "--- Deleting target groups ---"
for tg in "${PROJECT_NAME}-recs-tg" "${PROJECT_NAME}-recs-nlb-alb"; do
  arn="$(aws elbv2 describe-target-groups --names "${tg}" \
    --query 'TargetGroups[0].TargetGroupArn' --output text --region "${AWS_REGION}" 2>/dev/null || true)"
  if [[ -n "${arn}" && "${arn}" != "None" ]]; then
    aws elbv2 delete-target-group --target-group-arn "${arn}" --region "${AWS_REGION}" || true
  fi
done

echo "--- Deleting API Gateway ---"
API_ID="$(aws apigateway get-rest-apis --region "${AWS_REGION}" \
  --query "items[?name=='${PROJECT_NAME}-recommendations-api'].id | [0]" --output text 2>/dev/null || true)"
if [[ -n "${API_ID}" && "${API_ID}" != "None" ]]; then
  aws apigateway delete-rest-api --rest-api-id "${API_ID}" --region "${AWS_REGION}" || true
fi

VPC_LINK_ID="$(aws apigateway get-vpc-links --region "${AWS_REGION}" \
  --query "items[?name=='${PROJECT_NAME}-recommendations-vpclink'].id | [0]" --output text 2>/dev/null || true)"
if [[ -n "${VPC_LINK_ID}" && "${VPC_LINK_ID}" != "None" ]]; then
  aws apigateway delete-vpc-link --vpc-link-id "${VPC_LINK_ID}" --region "${AWS_REGION}" || true
fi

echo "--- Deleting SageMaker model packages ---"
for group in "purchase-propensity-model-group" "${PROJECT_NAME}-integration-model-group"; do
  arns="$(aws sagemaker list-model-packages \
    --model-package-group-name "${group}" \
    --region "${AWS_REGION}" \
    --query 'ModelPackageSummaryList[].ModelPackageArn' \
    --output text 2>/dev/null || true)"
  for arn in ${arns}; do
    [[ -z "${arn}" || "${arn}" == "None" ]] && continue
    aws sagemaker delete-model-package --model-package-name "${arn}" --region "${AWS_REGION}" || true
  done
  aws sagemaker delete-model-package-group \
    --model-package-group-name "${group}" --region "${AWS_REGION}" 2>/dev/null || true
done

echo "--- Emptying and deleting S3 buckets ---"
for bucket in "${DATA_BUCKET}" "${MODELS_BUCKET}"; do
  if aws s3api head-bucket --bucket "${bucket}" 2>/dev/null; then
    aws s3 rm "s3://${bucket}" --recursive --region "${AWS_REGION}" || true
    aws s3api delete-bucket --bucket "${bucket}" --region "${AWS_REGION}" || true
  fi
done

echo "--- Deleting DynamoDB tables ---"
for table in "${PROJECT_NAME}-predictions" "${PROJECT_NAME}-integration-predictions"; do
  aws dynamodb delete-table --table-name "${table}" --region "${AWS_REGION}" 2>/dev/null || true
done

echo "--- Deleting CloudWatch log groups ---"
for lg in \
  "/ecs/${PROJECT_NAME}/model-train" \
  "/ecs/${PROJECT_NAME}/model-predict" \
  "/ecs/${PROJECT_NAME}/recommendations-api" \
  "/ecs/${PROJECT_NAME}/model-drift-monitor"; do
  aws logs delete-log-group --log-group-name "${lg}" --region "${AWS_REGION}" 2>/dev/null || true
done

echo "--- Deleting ECR repositories ---"
for repo in \
  "${PROJECT_NAME}-model-train" \
  "${PROJECT_NAME}-model-predict" \
  "${PROJECT_NAME}-recommendations-api" \
  "${PROJECT_NAME}-model-drift-monitor"; do
  aws ecr delete-repository --repository-name "${repo}" --force --region "${AWS_REGION}" 2>/dev/null || true
done

echo "--- Deleting SNS topic ---"
TOPIC_ARN="$(aws sns list-topics --region "${AWS_REGION}" \
  --query "Topics[?contains(TopicArn, ':${PROJECT_NAME}-model-drift-alerts')].TopicArn | [0]" \
  --output text 2>/dev/null || true)"
if [[ -n "${TOPIC_ARN}" && "${TOPIC_ARN}" != "None" ]]; then
  aws sns delete-topic --topic-arn "${TOPIC_ARN}" --region "${AWS_REGION}" || true
fi

echo "--- Deleting SSM parameter ---"
aws ssm delete-parameter \
  --name "/${PROJECT_NAME}/recommendations-api/api-key" \
  --region "${AWS_REGION}" 2>/dev/null || true

echo "--- Deleting ECS clusters ---"
sleep 15
for cluster in \
  "${PROJECT_NAME}-recommendations-api" \
  "${PROJECT_NAME}-model-train" \
  "${PROJECT_NAME}-model-predict" \
  "${PROJECT_NAME}-model-drift-monitor"; do
  aws ecs delete-cluster --cluster "${cluster}" --region "${AWS_REGION}" 2>/dev/null || true
done

echo "--- Deleting security groups ---"
VPC_ID="$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text --region "${AWS_REGION}")"
for sg_name in \
  "${PROJECT_NAME}-recommendations-api-ecs" \
  "${PROJECT_NAME}-recommendations-alb" \
  "${PROJECT_NAME}-model-train-ecs" \
  "${PROJECT_NAME}-model-predict-ecs" \
  "${PROJECT_NAME}-model-drift-monitor-ecs"; do
  sg_id="$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${sg_name}" "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[0].GroupId' --output text --region "${AWS_REGION}" 2>/dev/null || true)"
  if [[ -n "${sg_id}" && "${sg_id}" != "None" ]]; then
    aws ec2 delete-security-group --group-id "${sg_id}" --region "${AWS_REGION}" 2>/dev/null || true
  fi
done

echo "--- Detaching and deleting IAM roles ---"
for role in "${PROJECT_NAME}-ecs-task-execution" "${PROJECT_NAME}-ecs-task"; do
  aws iam detach-role-policy \
    --role-name "${role}" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" \
    2>/dev/null || true
  aws iam delete-role-policy --role-name "${role}" --policy-name "${PROJECT_NAME}-ecs-task" 2>/dev/null || true
  aws iam delete-role --role-name "${role}" 2>/dev/null || true
done

echo "--- Clearing Terraform state (keeping backend) ---"
ADDRS="$(terraform state list 2>/dev/null | grep -v '^data\.' | tr '\n' ' ' || true)"
if [[ -n "${ADDRS// /}" ]]; then
  # shellcheck disable=SC2086
  terraform state rm -lock=false ${ADDRS} || true
fi

echo "--- Applying fresh stack ---"
terraform apply -auto-approve -input=false \
  -var="image_tag=${IMAGE_TAG}" \
  -var="aws_region=${AWS_REGION}" \
  -var="run_model_predict_on_apply=false" \
  -var="run_model_train_on_apply=false" \
  -var="run_model_drift_monitor_on_apply=false"

echo "=== Fast reset completed ==="
