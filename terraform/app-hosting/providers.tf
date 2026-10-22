# Standard AWS credential resolution (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/
# AWS_REGION from the environment -- deploy.py exports these from
# credentials.env). No explicit region here so AWS_REGION drives it.
provider "aws" {}
