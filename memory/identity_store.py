# memory/identity_store.py
"""Domain store for identity resolution."""
import sqlite3
from datetime import datetime
from typing import Optional


class IdentityStore:
    """Manages identity linking and resolution across providers."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def link_identity(
        self,
        canonical_name: str,
        provider: str,
        provider_id: str,
        display_name: str = "",
        email: str = "",
        metadata: str = "",
    ) -> dict:
        """Link a provider identity to a canonical name. Upserts on (provider, provider_id)."""
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO identities (canonical_name, provider, provider_id, display_name, email, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider, provider_id) DO UPDATE SET
                   canonical_name=excluded.canonical_name,
                   display_name=excluded.display_name,
                   email=excluded.email,
                   metadata=excluded.metadata,
                   updated_at=excluded.updated_at""",
            (canonical_name, provider, provider_id, display_name, email, metadata, now, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM identities WHERE provider=? AND provider_id=?",
            (provider, provider_id),
        ).fetchone()
        return self._row_to_identity_dict(row)

    def unlink_identity(self, provider: str, provider_id: str) -> dict:
        """Remove an identity link. Returns status dict."""
        cursor = self.conn.execute(
            "DELETE FROM identities WHERE provider=? AND provider_id=?",
            (provider, provider_id),
        )
        self.conn.commit()
        if cursor.rowcount > 0:
            return {"status": "unlinked", "provider": provider, "provider_id": provider_id}
        return {"status": "not_found", "provider": provider, "provider_id": provider_id}

    def get_identity(self, canonical_name: str) -> list[dict]:
        """Get all linked identities for a canonical name."""
        rows = self.conn.execute(
            "SELECT * FROM identities WHERE canonical_name=? ORDER BY provider",
            (canonical_name,),
        ).fetchall()
        return [self._row_to_identity_dict(r) for r in rows]

    def search_identity(self, query: str) -> list[dict]:
        """Search identities by canonical_name, display_name, email, or provider_id."""
        rows = self.conn.execute(
            """SELECT * FROM identities
               WHERE canonical_name LIKE ? OR display_name LIKE ? OR email LIKE ? OR provider_id LIKE ?
               ORDER BY canonical_name""",
            (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [self._row_to_identity_dict(r) for r in rows]

    def resolve_sender(self, provider: str, sender_id_or_email: str) -> Optional[str]:
        """Resolve a sender to a canonical name. Tries provider_id first, then email."""
        row = self.conn.execute(
            "SELECT canonical_name FROM identities WHERE provider=? AND provider_id=?",
            (provider, sender_id_or_email),
        ).fetchone()
        if row:
            return row["canonical_name"]
        row = self.conn.execute(
            "SELECT canonical_name FROM identities WHERE email=?",
            (sender_id_or_email,),
        ).fetchone()
        if row:
            return row["canonical_name"]
        return None

    def resolve_handle_to_name(self, handle: str) -> dict:
        """Resolve a phone/email handle to a canonical name via the identity store."""
        handle = (handle or "").strip()
        if not handle:
            return {"canonical_name": None, "match_type": None, "all_matches": []}

        # 1. Exact imessage provider match
        row = self.conn.execute(
            "SELECT canonical_name FROM identities WHERE provider='imessage' AND provider_id=?",
            (handle,),
        ).fetchone()
        if row:
            return {
                "canonical_name": row["canonical_name"],
                "match_type": "imessage_provider",
                "all_matches": [row["canonical_name"]],
            }

        # 2. Exact email match
        row = self.conn.execute(
            "SELECT canonical_name FROM identities WHERE email=?",
            (handle,),
        ).fetchone()
        if row:
            return {
                "canonical_name": row["canonical_name"],
                "match_type": "email",
                "all_matches": [row["canonical_name"]],
            }

        # 3. Fuzzy search by provider_id
        rows = self.conn.execute(
            "SELECT DISTINCT canonical_name FROM identities WHERE provider_id LIKE ?",
            (f"%{handle}%",),
        ).fetchall()
        if rows:
            names = [r["canonical_name"] for r in rows]
            return {
                "canonical_name": names[0],
                "match_type": "fuzzy_provider_id",
                "all_matches": names,
            }

        return {"canonical_name": None, "match_type": None, "all_matches": []}

    def _row_to_identity_dict(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "canonical_name": row["canonical_name"],
            "provider": row["provider"],
            "provider_id": row["provider_id"],
            "display_name": row["display_name"],
            "email": row["email"],
            "metadata": row["metadata"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
