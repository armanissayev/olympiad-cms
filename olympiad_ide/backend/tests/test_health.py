def test_health_reports_database_readiness(api) -> None:
    response = api.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "olympiad-ide-api",
        "status": "ok",
        "version": "0.2.0",
    }
