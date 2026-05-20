from uuid import uuid4

from app.models import BrandSettings, Company
from app.services.settings import create_default_workspace, ensure_brand_settings


class FakeSession:
    def __init__(self, scalar_result=None) -> None:
        self.added = []
        self.flush_count = 0
        self.scalar_calls = 0
        self.scalar_result = scalar_result

    def add(self, record) -> None:
        self.added.append(record)

    def flush(self) -> None:
        self.flush_count += 1
        for record in self.added:
            if isinstance(record, Company) and record.id is None:
                record.id = uuid4()

    def scalar(self, _query):
        self.scalar_calls += 1
        return self.scalar_result


def test_default_workspace_keeps_brand_on_company_relationship() -> None:
    db = FakeSession()
    user_id = uuid4()
    user = type(
        "UserStub",
        (),
        {
            "id": user_id,
            "email": "admin@example.com",
            "email_normalized": "admin@example.com",
            "first_name": "Admin",
            "last_name": "User",
        },
    )()

    company = create_default_workspace(db, user)
    brand = ensure_brand_settings(db, company)

    assert brand is company.brand_settings
    assert brand.workspace_name == "Brain Assistant Workspace"
    assert brand.assistant_name == "Brain Assistant"
    assert db.scalar_calls == 0
    assert not any(isinstance(record, BrandSettings) for record in db.added)


def test_ensure_brand_settings_reuses_existing_database_row() -> None:
    company_id = uuid4()
    company = Company(id=company_id, created_by_user_id=uuid4())
    existing = BrandSettings(company_id=company_id, workspace_name="Existing workspace")
    db = FakeSession(scalar_result=existing)

    brand = ensure_brand_settings(db, company)

    assert brand is existing
    assert company.brand_settings is existing
    assert db.scalar_calls == 1
    assert db.flush_count == 0
