"""Документы операции: владение, сохранение, замена чека и атомарность загрузки."""
from datetime import date

import pytest

from app.domain.attachments import MAX_FILE_BYTES, AttachmentError, document
from tests.test_api import _login

PDF = b'%PDF-1.4\nprivate document bytes\n%%EOF'


@pytest.fixture
def payment(client):
    headers = _login(client, 'alice')
    company = client.post('/api/companies', headers=headers, json={'name': 'Documents test'}).json()
    response = client.post(f"/api/companies/{company['id']}/operations", headers=headers, json={
        'op_date': date.today().isoformat(), 'amount': '12.50', 'direction': 'out',
        'counterparty_name': 'Supplier', 'purpose': 'Invoice 5', 'balance_eod': '100.00',
    })
    assert response.status_code == 201
    return headers, response.json()['id']


def upload(client, headers, operation_id, kind='receipt', files=None):
    return client.post(f'/api/operations/{operation_id}/attachments', headers=headers,
                       data={'kind': kind}, files=files or [('files', ('receipt.pdf', PDF, 'text/html'))])


def test_documents_roundtrip_and_atomic_receipt_replacement(client, payment):
    headers, operation_id = payment
    first = upload(client, headers, operation_id)
    assert first.status_code == 201
    receipt = first.json()[0]
    assert receipt['previewable'] and receipt['content_type'] == 'application/pdf'
    assert receipt['size_bytes'] == len(PDF) and 'content' not in receipt
    assert client.get(f"/api/attachments/{receipt['id']}/file", headers=headers).content == PDF
    preview = client.get(f"/api/attachments/{receipt['id']}/file?inline=true", headers=headers)
    assert preview.status_code == 200 and preview.headers['content-disposition'].startswith('inline;')
    assert preview.headers['cache-control'] == 'no-store'
    related = upload(client, headers, operation_id, 'related', [('files', ('акт.txt', b'Act text', 'text/plain'))])
    assert related.status_code == 201 and len(related.json()) == 2
    act = next(item for item in related.json() if item['kind'] == 'related')
    assert not act['previewable']
    assert client.get(f"/api/attachments/{act['id']}/file?inline=true", headers=headers).status_code == 415
    download = client.get(f"/api/attachments/{act['id']}/file", headers=headers)
    assert download.content == b'Act text' and 'filename*=UTF-8' in download.headers['content-disposition']
    replaced = upload(client, headers, operation_id)
    assert replaced.status_code == 201
    assert len(replaced.json()) == 2 and sum(item['kind'] == 'receipt' for item in replaced.json()) == 1
    assert client.get(f"/api/attachments/{receipt['id']}/file", headers=headers).status_code == 404
    assert client.delete(f"/api/attachments/{act['id']}", headers=headers).status_code == 204
    assert client.get(f'/api/operations/{operation_id}/attachments', headers=headers).json() == [
        item for item in replaced.json() if item['kind'] == 'receipt']


def test_another_user_cannot_read_change_or_delete_documents(client, payment):
    headers, operation_id = payment
    attachment = upload(client, headers, operation_id).json()[0]
    other = _login(client, 'bob')
    assert client.get(f'/api/operations/{operation_id}/attachments', headers=other).status_code == 404
    assert upload(client, other, operation_id).status_code == 404
    assert client.get(f"/api/attachments/{attachment['id']}/file", headers=other).status_code == 404
    assert client.delete(f"/api/attachments/{attachment['id']}", headers=other).status_code == 404
    assert client.get(f"/api/attachments/{attachment['id']}/file", headers=headers).content == PDF
    assert client.get(f'/api/operations/{operation_id}/attachments').status_code == 401


def test_invalid_batch_does_not_partially_save_or_replace_existing_receipt(client, payment):
    headers, operation_id = payment
    original = upload(client, headers, operation_id).json()
    invalid = upload(client, headers, operation_id, 'related', [
        ('files', ('good.txt', b'valid', 'text/plain')), ('files', ('bad.exe', b'invalid', 'application/octet-stream'))])
    assert invalid.status_code == 422
    assert upload(client, headers, operation_id, files=[('files', ('fake.pdf', b'HTML', 'application/pdf'))]).status_code == 422
    assert client.get(f'/api/operations/{operation_id}/attachments', headers=headers).json() == original


def test_upload_size_and_number_limits(client, payment):
    headers, operation_id = payment
    assert upload(client, headers, operation_id, 'related', [
        ('files', ('large.txt', b'x' * (MAX_FILE_BYTES + 1), 'text/plain'))]).status_code == 413
    assert upload(client, headers, operation_id, 'related', [
        ('files', (f'{index}.txt', b'x', 'text/plain')) for index in range(11)]).status_code == 422
    assert client.get(f'/api/operations/{operation_id}/attachments', headers=headers).json() == []


@pytest.mark.parametrize('filename,content', [
    ('empty.txt', b''), ('bad.exe', b'x'), ('bad\r\n.txt', b'x'), ('fake.png', b'not PNG'),
])
def test_document_validation(filename, content):
    with pytest.raises(AttachmentError):
        document(filename, content)


def test_filename_is_only_a_display_name():
    assert document(r'C:\fakepath\акт.txt', b'act').filename == 'акт.txt'
