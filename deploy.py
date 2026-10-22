#!/usr/bin/env python3
"""Deploy the Confluent Cloud + AWS stack for this demo, stage by stage.

Three independent Terraform stacks, applied (or destroyed) via --stage:
  base          terraform/base -- Confluent environment, Basic cluster,
                service account/API keys, tickets.raw topic. Also syncs
                app/.env from its outputs so `cd app && uv run python -m
                support_portal` picks up fresh credentials automatically.
  app           terraform/app-hosting -- builds the app's Docker image,
                pushes it to ECR, and applies Amazon ECS Express Mode (a
                Fargate service + ALB + TLS from one Terraform resource).
                Requires `base` to already be applied.
  intelligence  terraform/confluent-intelligence -- Flink compute pool,
                ticket enrichment/metrics statements, RTCE key, and
                (opt-in via TF_VAR_intelligence_enable_bedrock_model /
                TF_VAR_intelligence_enable_agent in credentials.env) the
                TRIAGEAGENT pipeline. Requires `base`; auto-wires its MCP
                connection to `app`'s ingress URL once that stage has
                been applied.
  all           base -> app -> intelligence, in order.

Credentials come from credentials.env (see credentials.env.example), not
a per-directory terraform.tfvars, so the same file drives every stage.

Usage:
  python3 deploy.py                        # --stage base (default)
  python3 deploy.py --stage app            # build/push/deploy the app to AWS
  python3 deploy.py --stage intelligence   # apply the Flink/agent pipeline
  python3 deploy.py --stage all            # all three, in order

  python3 deploy.py --stage intelligence --destroy   # destroy one stage
  python3 deploy.py --stage all --destroy            # destroy all three,
                                                       # in reverse order
"""

# Defers annotation evaluation to strings, so `str | None`-style hints
# below don't fail on the plain system `python3` this script is meant to
# be run with directly (no venv) -- confirmed needed on this machine's
# python3 (3.9), which predates PEP 604 union syntax.
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_DIR = ROOT / "terraform" / "base"
APP_HOSTING_DIR = ROOT / "terraform" / "app-hosting"
INTELLIGENCE_DIR = ROOT / "terraform" / "confluent-intelligence"
APP_DIR = ROOT / "app"
CREDENTIALS_FILE = ROOT / "credentials.env"
CREDENTIALS_EXAMPLE = ROOT / "credentials.env.example"
APP_ENV_FILE = ROOT / "app" / ".env"
APP_ENV_EXAMPLE = ROOT / "app" / ".env.example"

REQUIRED_CREDENTIALS = ("TF_VAR_confluent_cloud_api_key", "TF_VAR_confluent_cloud_api_secret")
IGNORED_DIR_NAMES = {".venv", "__pycache__", ".pytest_cache"}

STAGE_DIRS = {"base": BASE_DIR, "app": APP_HOSTING_DIR, "intelligence": INTELLIGENCE_DIR}
STAGE_ORDER = ("base", "app", "intelligence")


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser -- skips blank lines and #-comments."""
    values = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_credentials(require_aws: bool = False) -> dict[str, str]:
    if not CREDENTIALS_FILE.exists():
        print(f"Error: {CREDENTIALS_FILE.name} not found.")
        print(f"Copy {CREDENTIALS_EXAMPLE.name} to {CREDENTIALS_FILE.name} and fill in your Confluent Cloud API key/secret.")
        sys.exit(1)

    creds = load_env_file(CREDENTIALS_FILE)
    missing = [key for key in REQUIRED_CREDENTIALS if not creds.get(key)]

    if require_aws:
        if not creds.get("AWS_REGION"):
            missing.append("AWS_REGION")
        has_profile = bool(creds.get("AWS_PROFILE"))
        has_keys = bool(creds.get("AWS_ACCESS_KEY_ID")) and bool(creds.get("AWS_SECRET_ACCESS_KEY"))
        if not has_profile and not has_keys:
            print(f"Error: {CREDENTIALS_FILE.name} needs either AWS_PROFILE, or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY, to authenticate with AWS.")
            sys.exit(1)

    if missing:
        print(f"Error: {CREDENTIALS_FILE.name} is missing: {', '.join(missing)}")
        sys.exit(1)

    enable_bedrock = creds.get("TF_VAR_intelligence_enable_bedrock_model", "").lower() == "true"
    enable_agent = creds.get("TF_VAR_intelligence_enable_agent", "").lower() == "true"
    if enable_agent and not enable_bedrock:
        print(f"Error: {CREDENTIALS_FILE.name} has TF_VAR_intelligence_enable_agent=true but TF_VAR_intelligence_enable_bedrock_model is not true (required together).")
        sys.exit(1)
    # Bedrock credentials themselves are no longer user-supplied --
    # terraform/confluent-intelligence creates its own dedicated IAM user
    # (see bedrock_iam.tf) using the AWS_* creds already validated above
    # by require_aws, whenever intelligence_enable_bedrock_model=true.

    return creds


def run_terraform_apply(
    env_path: Path,
    extra_env: dict[str, str],
    target: str | list[str] | None = None,
    extra_vars: dict[str, str] | None = None,
) -> None:
    tf_env = {**os.environ, **extra_env}
    for key, value in (extra_vars or {}).items():
        tf_env[f"TF_VAR_{key}"] = value
    label = env_path.relative_to(ROOT)
    targets = [target] if isinstance(target, str) else (target or [])

    print(f"\n=== terraform init ({label}) ===")
    subprocess.run(["terraform", "init"], cwd=env_path, env=tf_env, check=True)

    apply_cmd = ["terraform", "apply"] + [f"-target={t}" for t in targets]

    target_suffix = "".join(f" -target={t}" for t in targets)
    print(f"\n=== terraform apply ({label}{target_suffix}) ===")
    # No -auto-approve: terraform shows its own plan and asks for
    # confirmation interactively, so changes are never applied silently.
    subprocess.run(apply_cmd, cwd=env_path, env=tf_env, check=True)


def run_terraform_destroy(env_path: Path, extra_env: dict[str, str]) -> None:
    tf_env = {**os.environ, **extra_env}
    label = env_path.relative_to(ROOT)

    print(f"\n=== terraform init ({label}) ===")
    subprocess.run(["terraform", "init"], cwd=env_path, env=tf_env, check=True)

    print(f"\n=== terraform destroy ({label}) ===")
    # No -auto-approve, same philosophy as run_terraform_apply.
    subprocess.run(["terraform", "destroy"], cwd=env_path, env=tf_env, check=True)


def run_terraform_output(env_path: Path) -> dict:
    """terraform output -json, unwrapped from {"value": ...} to plain
    values. Pattern from
    demo-confluent-intelligence-f1/scripts/common/terraform.py."""
    result = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=env_path,
        capture_output=True,
        text=True,
        check=True,
    )
    outputs = json.loads(result.stdout)
    return {key: value["value"] for key, value in outputs.items()}


def check_prereq_state(dir_path: Path, missing_stage_hint: str) -> None:
    """Fails fast with a friendly message if a stage this one depends on
    hasn't been applied yet, instead of surfacing a raw Terraform
    remote_state/data-source error mid-apply."""
    if not (dir_path / "terraform.tfstate").exists():
        print(f"Error: {dir_path.relative_to(ROOT)}/terraform.tfstate not found.")
        print(f"Run `python3 deploy.py --stage {missing_stage_hint}` first.")
        sys.exit(1)


def strip_protocol_scheme(bootstrap_servers: str) -> str:
    """confluent_kafka_cluster.bootstrap_endpoint comes back as
    'SASL_SSL://host:port' -- confluent-kafka's bootstrap.servers config
    wants bare host:port (security.protocol is a separate config key)."""
    if "://" in bootstrap_servers:
        return bootstrap_servers.split("://", 1)[1]
    return bootstrap_servers


def sync_app_env(app_env: dict[str, str]) -> list[str]:
    """Merge Terraform's app_env output onto app/.env, overwriting only
    the CC_* keys it provides and preserving everything else (so a
    customized ADMIN_TOKEN, etc. survives a re-run)."""
    app_env = dict(app_env)
    app_env["CC_BOOTSTRAP_SERVERS"] = strip_protocol_scheme(app_env["CC_BOOTSTRAP_SERVERS"])

    base_file = APP_ENV_FILE if APP_ENV_FILE.exists() else APP_ENV_EXAMPLE
    existing_lines = base_file.read_text().splitlines()

    written_keys = []
    seen_keys = set()
    new_lines = []
    for raw_line in existing_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            new_lines.append(raw_line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in app_env:
            new_lines.append(f"{key}={app_env[key]}")
            written_keys.append(key)
            seen_keys.add(key)
        else:
            new_lines.append(raw_line)

    missing_keys = [key for key in app_env if key not in seen_keys]
    if missing_keys:
        new_lines.append("")
        new_lines.append("# --- Added by deploy.py ---")
        for key in missing_keys:
            new_lines.append(f"{key}={app_env[key]}")
            written_keys.append(key)

    APP_ENV_FILE.write_text("\n".join(new_lines) + "\n")
    return written_keys


def compute_image_tag() -> str:
    """Stable content hash of app/ (excluding venvs/caches), so the ECR
    tag only changes when the app's code actually changes."""
    hasher = hashlib.sha1()
    for path in sorted(APP_DIR.rglob("*")):
        if not path.is_file() or IGNORED_DIR_NAMES & set(path.relative_to(APP_DIR).parts):
            continue
        hasher.update(str(path.relative_to(APP_DIR)).encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()[:12]


def docker_build_and_push(ecr_repository_url: str, region: str, env: dict[str, str]) -> str:
    tag = compute_image_tag()
    image_uri = f"{ecr_repository_url}:{tag}"
    aws_env = {**os.environ, **env}

    print(f"\n=== docker build ({image_uri}) ===")
    # Fargate runs x86_64 by default -- without --platform, a build on
    # Apple Silicon produces an arm64 image that fails on ECS with
    # "exec format error" (confirmed live via the container's CloudWatch
    # logs), since ECS Express Mode doesn't expose an ARM64/Graviton
    # runtime_platform option to match it instead.
    subprocess.run(
        ["docker", "build", "--platform", "linux/amd64", "-t", image_uri, str(APP_DIR)],
        check=True,
    )

    print("\n=== docker login (ECR) ===")
    # Needs AWS_PROFILE/credentials from credentials.env, not just
    # whatever's already in deploy.py's own shell -- easy to miss since
    # docker itself doesn't need AWS auth, only this one `aws` call does.
    password = subprocess.run(
        ["aws", "ecr", "get-login-password", "--region", region],
        env=aws_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    registry = ecr_repository_url.split("/", 1)[0]
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password,
        text=True,
        check=True,
    )

    print(f"\n=== docker push ({image_uri}) ===")
    subprocess.run(["docker", "push", image_uri], check=True)
    return image_uri


def ensure_admin_token(creds: dict[str, str]) -> str:
    """Generated once, persisted to credentials.env, and reused on every
    later app-stage run so a bookmarked console URL/token stays valid
    across redeploys."""
    token = creds.get("TF_VAR_app_admin_token")
    if token:
        return token

    token = secrets.token_urlsafe(16)
    with CREDENTIALS_FILE.open("a") as f:
        f.write(f"\nTF_VAR_app_admin_token={token}\n")
    creds["TF_VAR_app_admin_token"] = token
    print(f"Generated a new admin token and saved it to {CREDENTIALS_FILE.name}.")
    return token


def deploy_base(creds: dict[str, str]) -> dict:
    base_env = {key: value for key, value in creds.items() if key.startswith("TF_VAR_")}
    try:
        run_terraform_apply(BASE_DIR, base_env)
    except subprocess.CalledProcessError:
        print("\nTerraform apply did not complete (failed, or cancelled at the confirmation prompt).")
        print("app/.env was not touched. Fix the issue above and re-run `python3 deploy.py --stage base`.")
        sys.exit(1)

    print("\n=== Wiring app/.env from terraform outputs ===")
    outputs = run_terraform_output(BASE_DIR)
    written_keys = sync_app_env(outputs["app_env"])
    print(f"Wrote {len(written_keys)} keys to {APP_ENV_FILE.relative_to(ROOT)}: {', '.join(sorted(written_keys))}")
    print(f"\nEnvironment: {outputs['environment_id']}   Cluster: {outputs['cluster_id']}")
    return outputs


def deploy_app_hosting(creds: dict[str, str]) -> dict:
    check_prereq_state(BASE_DIR, "base")

    full_env = dict(creds)
    region = creds["AWS_REGION"]
    admin_token = ensure_admin_token(creds)
    full_env["TF_VAR_app_admin_token"] = admin_token

    # Preserve the live service across redeploys: pass 1 only targets the ECR
    # repo + CloudFront distribution, but Terraform still evaluates the whole
    # config to plan that target, and leaving app_image_uri/
    # app_mcp_allowed_hosts at their bootstrap defaults ("" / "localhost:*,
    # 127.0.0.1:*") plans to DESTROY the live ECS service, since its count is
    # `var.app_image_uri != "" ? 1 : 0` (main.tf). Confirmed live: this
    # happened for real, destroying the running service and rotating its
    # ingress hostname, which is why MCP_ALLOWED_HOSTS (pass 3 below) kept
    # losing sync. Only recompute/pass these through when the service already
    # exists -- on a genuine first deploy, outputs.tf's ingress_url won't
    # exist yet and pass 1 should keep its current empty-default behavior.
    pass1_vars = {}
    prebuilt_image_uri = None
    try:
        existing = run_terraform_output(APP_HOSTING_DIR)
    except subprocess.CalledProcessError:
        existing = {}
    if existing.get("ingress_url") and existing.get("ecr_repository_url"):
        cloudfront_hostname = existing["app_public_url"].split("://", 1)[-1].split("/", 1)[0]
        ingress_hostname = existing["ingress_url"].split("://", 1)[-1].split("/", 1)[0]
        # Redeploy: build and push the image BEFORE pass 1. The targeted
        # apply below still updates the live ECS service (the CloudFront
        # origin depends on it), so it must reference a tag that already
        # exists in ECR. Confirmed live (28 Sept): with the push done after
        # pass 1, a code change made pass 1 point the service at a tag not
        # yet pushed -> CannotPullContainerError -> circuit breaker rollback.
        prebuilt_image_uri = docker_build_and_push(existing["ecr_repository_url"], region, full_env)
        pass1_vars = {
            "app_image_uri": prebuilt_image_uri,
            "app_mcp_allowed_hosts": f"localhost:*,127.0.0.1:*,{cloudfront_hostname},{ingress_hostname}",
        }

    try:
        # Pass 1: create just the ECR repo and the CloudFront
        # distribution (cloudfront.tf), so the image can be built and
        # pushed against a real URI, and so app_public_url is known,
        # before the Express service exists at all. app_image_uri is
        # left at its "" default here on a first deploy, which keeps
        # aws_ecs_express_gateway_service.app's count at 0 (see
        # main.tf) -- it isn't touched by this targeted apply. On a
        # redeploy, pass1_vars (above) carries the current image/allowlist
        # through instead, so this targeted apply can't regress them.
        run_terraform_apply(
            APP_HOSTING_DIR,
            full_env,
            target=["aws_ecr_repository.app", "aws_cloudfront_distribution.app"],
            extra_vars=pass1_vars,
        )
        pre_outputs = run_terraform_output(APP_HOSTING_DIR)
        image_uri = prebuilt_image_uri or docker_build_and_push(pre_outputs["ecr_repository_url"], region, full_env)

        app_public_url = pre_outputs["app_public_url"]
        if not app_public_url:
            print("\nWarning: could not read app_public_url from Terraform output.")
            print("Check `terraform output` in terraform/app-hosting and re-run with the hostname set manually if needed.")
            return pre_outputs
        cloudfront_hostname = app_public_url.split("://", 1)[-1].split("/", 1)[0]

        # Pass 2: full apply. Creates the Express service for the first
        # time, with MCP_ALLOWED_HOSTS set to the CloudFront domain known
        # from pass 1 -- and, in the same apply, flips the CloudFront
        # distribution's origin from its placeholder to the now-real
        # Express ingress endpoint.
        #
        # This *doesn't* fully allowlist the app yet: cloudfront.tf's
        # origin request policy (Managed-AllViewerExceptHostHeader, and
        # why) forwards the browser's real Origin header -- matching
        # cloudfront_hostname, good -- but always rewrites the Host
        # header it sends to the origin to the ALB's own ingress
        # hostname, which isn't known until this apply returns. Pass 3
        # adds that hostname too.
        # On a redeploy, pass 1 already applied the new image and the full
        # allowlist (CloudFront + current ingress). Dropping the ingress
        # hostname here and re-adding it in pass 3 cost two extra ~9-minute
        # ECS rollouts and left /mcp briefly rejecting CloudFront's Host
        # header (observed 28 Sept). Keep the pass-1 allowlist so pass 2 and
        # pass 3 are no-ops unless something else changed.
        pass2_hosts = pass1_vars.get(
            "app_mcp_allowed_hosts", f"localhost:*,127.0.0.1:*,{cloudfront_hostname}"
        )
        run_terraform_apply(
            APP_HOSTING_DIR,
            full_env,
            extra_vars={
                "app_image_uri": image_uri,
                "app_mcp_allowed_hosts": pass2_hosts,
            },
        )
        outputs = run_terraform_output(APP_HOSTING_DIR)
        ingress_url = outputs["ingress_url"]
        if not ingress_url:
            print("\nWarning: could not read the ingress URL from Terraform output.")
            print("Check `terraform output` in terraform/app-hosting and re-run with the hostname set manually if needed.")
            return outputs
        ingress_hostname = ingress_url.split("://", 1)[-1].split("/", 1)[0]

        # Pass 3: re-apply with the raw ingress hostname also allowlisted
        # -- CloudFront's origin always sends this as the Host header
        # (see above), so the /mcp endpoint's Host check needs it too.
        # Only restarts the one task, doesn't rebuild or touch the
        # CloudFront distribution.
        run_terraform_apply(
            APP_HOSTING_DIR,
            full_env,
            extra_vars={
                "app_image_uri": image_uri,
                "app_mcp_allowed_hosts": f"localhost:*,127.0.0.1:*,{cloudfront_hostname},{ingress_hostname}",
            },
        )
    except subprocess.CalledProcessError:
        print("\nAWS deployment did not complete (failed, or cancelled at a confirmation prompt).")
        print("Fix the issue above and re-run `python3 deploy.py --stage app`.")
        sys.exit(1)

    outputs = run_terraform_output(APP_HOSTING_DIR)
    print("\n=== App deployed ===")
    print(f"URL:         {outputs['app_public_url']}")
    print(f"Admin token: {admin_token}")
    return outputs


def deploy_intelligence(creds: dict[str, str]) -> dict:
    check_prereq_state(BASE_DIR, "base")

    intelligence_env = {key: value for key, value in creds.items() if key.startswith("TF_VAR_")}
    # This stack's own `aws` provider (bedrock_iam.tf) needs plain AWS_*
    # auth too, but only when intelligence_enable_bedrock_model=true
    # actually creates AWS resources -- the common case (false) stays
    # AWS-credential-free, matching require_aws's own logic in main().
    # Always pass them: the aws provider is configured (and validates its
    # credentials) even when no AWS resource is planned.
    if True:
        for key in ("AWS_PROFILE", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            if key in creds:
                intelligence_env[key] = creds[key]

    try:
        # Single-pass apply is enough here: unlike the app stage, nothing
        # in this phase needs a value that's only known after its own
        # first apply -- app_public_url comes from app-hosting's state
        # (see terraform/confluent-intelligence/main.tf), not from a
        # bootstrap step within this stage itself.
        run_terraform_apply(INTELLIGENCE_DIR, intelligence_env)
    except subprocess.CalledProcessError:
        print("\nTerraform apply did not complete (failed, or cancelled at the confirmation prompt).")
        print("Fix the issue above and re-run `python3 deploy.py --stage intelligence`.")
        sys.exit(1)

    outputs = run_terraform_output(INTELLIGENCE_DIR)
    print("\n=== Confluent Intelligence deployed ===")
    print(f"Flink compute pool: {outputs.get('flink_compute_pool_id')}")
    if outputs.get("resolved_app_public_url"):
        print(f"Triage agent MCP endpoint: {outputs['resolved_app_public_url']}/mcp")
    return outputs


APPLY_FNS = {"base": deploy_base, "app": deploy_app_hosting, "intelligence": deploy_intelligence}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--stage",
        choices=["base", "app", "intelligence", "all"],
        default="base",
        help="Which stage(s) to apply. 'all' runs base -> app -> intelligence in dependency order.",
    )
    parser.add_argument(
        "--destroy",
        action="store_true",
        help="Destroy the selected stage(s) instead of applying them. With --stage all, destroys in reverse order (intelligence -> app -> base).",
    )
    args = parser.parse_args()

    print("=== DSWT2026 Support Portal -- deploy ===")

    stages = list(STAGE_ORDER) if args.stage == "all" else [args.stage]
    if args.destroy:
        stages = list(reversed(stages))

    require_aws = "app" in stages
    if "intelligence" in stages and CREDENTIALS_FILE.exists():
        # Peek at the flag before load_credentials parses (and validates)
        # the same file -- the intelligence stage only needs AWS auth
        # when intelligence_enable_bedrock_model=true (it creates its own
        # IAM user, see terraform/confluent-intelligence/bedrock_iam.tf).
        peek = load_env_file(CREDENTIALS_FILE)
        require_aws = require_aws or peek.get("TF_VAR_intelligence_enable_bedrock_model", "").lower() == "true"
    creds = load_credentials(require_aws=require_aws)

    for stage in stages:
        if args.destroy:
            # Full creds (not just TF_VAR_*), matching deploy_app_hosting's
            # own env -- the app stage's `terraform destroy` still needs
            # AWS_* auth for its provider.
            try:
                run_terraform_destroy(STAGE_DIRS[stage], creds)
            except subprocess.CalledProcessError:
                print(f"\nDestroy of terraform/{STAGE_DIRS[stage].name} did not complete.")
                sys.exit(1)
        else:
            APPLY_FNS[stage](creds)

    if not args.destroy and stages == ["base"]:
        print("\nNext:")
        print("  cd app && uv run python -m support_portal --disable-generator")


if __name__ == "__main__":
    main()
