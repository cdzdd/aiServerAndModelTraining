from uuid import uuid4

import pytest

from app.core.security import AuthError
from app.modules.auth.schemas import Actor


@pytest.mark.parametrize(
    "role,owner,assigned,allowed",
    [
        ("user", True, False, True),
        ("user", False, False, False),
        ("user", False, True, False),
        ("agent", False, False, False),
        ("agent", False, True, True),
        ("agent", True, False, True),
        ("admin", False, False, True),
    ],
)
def test_conversation_matrix(role, owner, assigned, allowed):
    from app.modules.auth.permissions import require_conversation_access

    actor = Actor(user_id=uuid4(), role=role)
    kwargs = {
        "owner_id": actor.user_id if owner else uuid4(),
        "assigned_agent_id": actor.user_id if assigned else None,
    }
    if allowed:
        require_conversation_access(actor, **kwargs)
    else:
        with pytest.raises(AuthError) as error:
            require_conversation_access(actor, **kwargs)
        assert error.value.status == 404


@pytest.mark.parametrize(
    "role,visibility,member,active,allowed",
    [
        ("user", "public", False, True, True),
        ("agent", "public", False, True, True),
        ("user", "restricted", False, True, False),
        ("agent", "restricted", False, True, False),
        ("user", "restricted", True, True, True),
        ("admin", "restricted", False, True, True),
        ("admin", "public", True, False, False),
        ("user", "public", True, False, False),
    ],
)
def test_knowledge_matrix(role, visibility, member, active, allowed):
    from app.modules.auth.permissions import require_knowledge_access

    actor = Actor(user_id=uuid4(), role=role)
    kwargs = {"visibility": visibility, "is_member": member, "is_active": active}
    if allowed:
        require_knowledge_access(actor, **kwargs)
    else:
        with pytest.raises(AuthError) as error:
            require_knowledge_access(actor, **kwargs)
        assert error.value.status == 404


def test_role_check_does_not_trust_request_fields(client, signed_in):
    response = client.get("/api/v1/admin/users", headers={"role": "admin"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
