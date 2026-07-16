import io
import zipfile
from pathlib import Path

import pytest

from django.conf import settings
from django.urls import reverse

from rdmo.conditions.models import Condition
from rdmo.domain.models import Attribute
from rdmo.options.models import Option, OptionSet
from rdmo.questions.models import Catalog, Page, Question, QuestionSet, Section
from rdmo.tasks.models import Task
from rdmo.views.models import View

users = (
    ('editor', 'editor'),
    ('reviewer', 'reviewer'),
    ('user', 'user'),
    ('api', 'api'),
    ('anonymous', None),
)

status_map = {
    'list': {
        'editor': 405, 'reviewer': 403, 'api': 405, 'user': 403, 'anonymous': 401
    },
    'create': {
        'editor': 200, 'reviewer': 403, 'api': 200, 'user': 403, 'anonymous': 401
    },
    'create_error': {
        'editor': 400, 'reviewer': 403, 'api': 400, 'user': 403, 'anonymous': 401
    }
}

urlnames = {
    'list': 'v1-management:upload-zip-list'
}

XML_ELEMENTS_DIR = Path(settings.BASE_DIR) / 'xml' / 'elements'


def build_zip(file_names, arcnames=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for index, file_name in enumerate(file_names):
            arcname = arcnames[index] if arcnames else Path(file_name).name
            zf.write(XML_ELEMENTS_DIR / file_name, arcname=arcname)
    buffer.seek(0)
    buffer.name = 'archive.zip'
    return buffer


@pytest.mark.parametrize('username,password', users)
def test_list(db, client, username, password):
    client.login(username=username, password=password)

    url = reverse(urlnames['list'])
    response = client.get(url)
    assert response.status_code == status_map['list'][username], response.json()


@pytest.mark.parametrize('username,password', users)
def test_create(db, client, username, password):
    client.login(username=username, password=password)

    zip_file = build_zip(['attributes.xml', 'conditions.xml', 'optionsets.xml',
                          'options.xml', 'catalog.xml', 'tasks.xml', 'views.xml'])

    url = reverse(urlnames['list'])
    response = client.post(url, {'file': zip_file})

    assert response.status_code == status_map['create'][username], response.json()
    if response.status_code == 200:
        models_in_response = {element['model'] for element in response.json()}
        assert {
            'domain.attribute', 'conditions.condition', 'options.optionset',
            'options.option', 'questions.catalog', 'tasks.task', 'views.view'
        } <= models_in_response


@pytest.mark.parametrize('username,password', users)
def test_create_import_create(db, client, username, password, delete_all_objects):
    delete_all_objects(Attribute, Condition, OptionSet, Option, Catalog, Section, Page, QuestionSet, Question,
                       Task, View)

    client.login(username=username, password=password)

    zip_file = build_zip(['attributes.xml', 'conditions.xml', 'optionsets.xml',
                          'options.xml', 'catalog.xml', 'tasks.xml', 'views.xml'])

    url = reverse(urlnames['list'])
    response = client.post(url, {'file': zip_file, 'import': 'true'})

    assert response.status_code == status_map['create'][username], response.json()
    if response.status_code == 200:
        for element in response.json():
            assert element.get('created') is False if username in ['reviewer', 'user'] else True
            assert element.get('updated') is False

        if username in ['editor', 'api']:
            # elements from all the merged files should have been created,
            # regardless of the (alphabetical) order in which they were read from the zip
            assert Attribute.objects.exists()
            assert Condition.objects.exists()
            assert OptionSet.objects.exists()
            assert Option.objects.exists()
            assert Catalog.objects.exists()
            assert Task.objects.exists()
            assert View.objects.exists()


@pytest.mark.parametrize('username,password', users)
def test_create_empty(db, client, username, password):
    client.login(username=username, password=password)

    url = reverse(urlnames['list'])
    response = client.post(url, {})
    assert response.status_code == status_map['create_error'][username], response.json()


@pytest.mark.parametrize('username,password', users)
def test_create_not_a_zip(db, client, username, password):
    client.login(username=username, password=password)

    buffer = io.BytesIO(b'this is not a zip file')
    buffer.name = 'archive.zip'

    url = reverse(urlnames['list'])
    response = client.post(url, {'file': buffer})

    assert response.status_code == status_map['create_error'][username], response.json()
    if response.status_code == 400:
        assert 'not a valid ZIP archive' in " ".join(response.json()['file'])


@pytest.mark.parametrize('username,password', users)
def test_create_zip_without_xml(db, client, username, password):
    client.login(username=username, password=password)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('readme.md', '# not an xml file')
    buffer.seek(0)
    buffer.name = 'archive.zip'

    url = reverse(urlnames['list'])
    response = client.post(url, {'file': buffer})

    assert response.status_code == status_map['create_error'][username], response.json()
    if response.status_code == 400:
        assert 'does not contain any XML files' in " ".join(response.json()['file'])


@pytest.mark.parametrize('username,password', users)
def test_create_error(db, client, username, password):
    client.login(username=username, password=password)

    zip_file = build_zip(['attributes.xml', 'legacy/catalog-error-key.xml'],
                         arcnames=['attributes.xml', 'catalog-error-key.xml'])

    url = reverse(urlnames['list'])
    response = client.post(url, {'file': zip_file})

    assert response.status_code == status_map['create_error'][username], response.json()
    if response.status_code == 400:
        response_msg = " ".join(response.json()['file'])
        assert 'catalog-error-key.xml' in response_msg
