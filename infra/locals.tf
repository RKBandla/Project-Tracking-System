locals {
  # Unique application identifier (participant code or random fallback)
  app_id   = try(trimspace(var.aws_app_code), "") != "" ? trimspace(var.aws_app_code) : random_id.this.hex
  app_tags = { participant = local.app_id, event = random_id.this.hex, app = "project-tracking-system" }
  # Whether we are running against LocalStack (account 000000000000)
  is_local = data.aws_caller_identity.this.id == "000000000000"
  public_route_table_ids = [
    for rt in data.aws_route_table.this :
    rt.id if length([for route in rt.routes : route if startswith(route.gateway_id, "igw-")]) > 0
  ]
  public_subnet_ids = sort(distinct(flatten([
    for rt_id in local.public_route_table_ids : [
      for assoc in data.aws_route_table.this[rt_id].associations :
      assoc.subnet_id if assoc.subnet_id != ""
    ]
  ])))
  private_subnet_ids = sort(tolist(setsubtract(data.aws_subnets.this.ids, local.public_subnet_ids)))
  # Python services: every backend/<name>/requirements.txt (folders starting with _ or . are skipped)
  backend_dirs_python = [
    for file in fileset(format("%s/../backend", path.module), "*/requirements.txt") :
    dirname(file) if !startswith(dirname(file), "_") && !startswith(dirname(file), ".")
  ]
  function_names = {
    for name in local.backend_dirs_python : name => {
      name             = name
      arch             = "x86_64"
      runtime          = "python3.13"
      handler          = "function.handler"
      path             = abspath(format("%s/../backend/%s", path.module, name))
      patterns         = ["!__pycache__/.*", "!\\..*"]
      pip_requirements = true
    }
  }
  function_origins = [
    for name, func in local.function_names : {
      name        = func.name
      origin_id   = format("lambda-%s", func.name)
      domain_name = replace(replace(module.lambda[name].lambda_function_url, "https://", ""), "/", "")
    }
  ]
  origin_id = format("%s-s3-origin-%s", var.aws_project, local.app_id)
  # Environment variables injected into every Lambda function
  env_vars = {
    APP_ID            = local.app_id
    APP_NAME          = format("%s-%s", var.aws_project, local.app_id)
    APP_REGION        = data.aws_region.this.region
    IS_LOCAL          = local.is_local ? "true" : "false"
    POSTGRES_HOST     = local.is_local ? coalesce(try(trimspace(var.aws_postgres_host), ""), "172.17.0.1") : try(one(aws_rds_cluster.this.*.endpoint), "")
    POSTGRES_PORT     = local.is_local ? "5432" : try(one(aws_rds_cluster.this.*.port), "")
    POSTGRES_NAME     = local.is_local ? "postgres" : try(one(aws_rds_cluster.this.*.database_name), "")
    POSTGRES_USER     = local.is_local ? "postgres" : try(one(aws_rds_cluster.this.*.master_username), "")
    POSTGRES_PASS     = local.is_local ? "postgres123" : try(one(aws_rds_cluster.this.*.master_password), "")
    JWT_SECRET        = random_password.jwt_secret.result
    ADMIN_EMAIL       = var.admin_email
    ADMIN_EMPLOYEE_ID = var.admin_employee_id
    ADMIN_PASSWORD    = random_password.admin.result
  }
  lambda_role_arn = format(
    "arn:%s:iam::%s:role/%s-lambda-%s-%s",
    data.aws_partition.this.partition, data.aws_caller_identity.this.id,
    var.aws_project, data.aws_region.this.region, local.app_id
  )
}
