terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.116"
    }
  }
  # stores state remotely — critical for team environments
  # comment this out on first run, set up the storage account manually first
  # then uncomment
  backend "azurerm" {
    resource_group_name  = "taskapi-tfstate-rg"
    storage_account_name = "taskapitfstate" # must be globally unique
    container_name       = "tfstate"
    key                  = "taskapi.terraform.state"
  }
}

provider "azurerm" {
  features {}
}
