"""Поиск должен учитывать русский регистр, владельца и пагинацию."""
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login


def test_search_is_case_insensitive_and_paginated(client):
    headers = _login(client, "alice")
    frame = make_company()
    frame.loc[frame.index[0], "counterparty_name"] = "Особенный Партнёр 100%"
    cid = _import(client, headers, to_case_csv(frame))["company"]["id"]
    endpoint = f"/api/companies/{cid}/operations/search"
    unique = client.post(endpoint, headers=headers, json={"query": "оСоБеНнЫй пАрТнЁр"})
    assert unique.status_code == 200 and len(unique.json()) == 1
    assert client.post(endpoint, headers=headers, json={"query": "100%"}).json() == unique.json()
    assert client.post(endpoint, headers=headers, json={"query": "%"}).json() == unique.json()

    all_rent = client.post(endpoint, headers=headers, json={"query": "аРеНдА"}).json()
    assert len(all_rent) > 1
    page = client.post(endpoint, headers=headers, json={"query": "аренда", "limit": 1, "offset": 1}).json()
    assert page == all_rent[1:2]
    assert client.post(endpoint, headers=headers, json={"query": "аренда", "category": "nonexistent"}).json() == []


def test_search_enforces_ownership_and_validation(client):
    alice, bob = _login(client, "alice"), _login(client, "bob")
    cid = _import(client, alice, to_case_csv(make_company()))["company"]["id"]
    endpoint = f"/api/companies/{cid}/operations/search"
    assert client.post(endpoint, headers=bob, json={"query": "аренда"}).status_code == 404
    assert client.post(endpoint, json={}).status_code == 401
    assert client.post(endpoint, headers=alice, json={"query": "x" * 121}).status_code == 422
    assert client.post(endpoint, headers=alice, json={"owner_id": "someone"}).status_code == 422
