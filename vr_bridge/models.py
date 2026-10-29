"""Additive tables: VR records never mutate existing training/program tables."""
from sqlalchemy import Column, Integer, JSON, String, UniqueConstraint
from database import Base


class VRConnection(Base):
    __tablename__ = "vr_connections"
    id = Column(String(64), primary_key=True)
    device_name = Column(String(80), nullable=False)
    secret_hash = Column(String(64), nullable=False)
    code_hash = Column(String(64), unique=True, nullable=True)
    expires_at = Column(Integer, nullable=False)
    # One active connection per web user; NULL permits multiple unbound devices.
    user_id = Column(String(64), unique=True, nullable=True)
    state = Column(String(16), nullable=False, default="pending")
    connected_at = Column(Integer, nullable=True)
    reference = Column(JSON, nullable=True)
    reference_updated_at = Column(Integer, nullable=True)


class VRResult(Base):
    __tablename__ = "vr_results"
    __table_args__ = (UniqueConstraint("user_id", "client_session_id"),)
    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), index=True, nullable=False)
    connection_id = Column(String(64), nullable=False)
    client_session_id = Column(String(80), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    data = Column(JSON, nullable=False)
    received_at = Column(Integer, nullable=False)


class VRPairing(Base):
    """Web-issued one-time code; no plaintext device secret or code is persisted."""
    __tablename__ = "vr_pairings"
    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), unique=True, nullable=False)
    code_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(Integer, nullable=False)
    reference = Column(JSON, nullable=True)
    state = Column(String(16), nullable=False, default="pending")
    connection_id = Column(String(64), nullable=True)
