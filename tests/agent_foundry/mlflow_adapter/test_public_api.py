"""Public-API export guarantees for the MLflow adapter."""


def test_mlflow_adapter_public_surface_is_exported():
    import agent_foundry.mlflow_adapter as mlflow_adapter
    from agent_foundry.mlflow_adapter import MLFLOW_TRANSLATIONS, enable

    expected = {
        "MLFLOW_TRANSLATIONS",
        "enable",
    }

    assert expected <= set(mlflow_adapter.__all__)
    assert mlflow_adapter.MLFLOW_TRANSLATIONS is MLFLOW_TRANSLATIONS
    assert mlflow_adapter.enable is enable


def test_testing_reset_helper_is_not_public():
    import agent_foundry.mlflow_adapter as mlflow_adapter

    assert "reset_for_testing" not in mlflow_adapter.__all__
