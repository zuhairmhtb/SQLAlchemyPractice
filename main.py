# =============================================================================
# main.py — Flask Demo: Models · Views · Routes · Middleware · Settings
# =============================================================================

# ── Standard library ──────────────────────────────────────────────────────────
import enum
import logging
import os
import uuid
from datetime import date, datetime
from typing import List, Optional

# ── Third-party ───────────────────────────────────────────────────────────────
import bcrypt
from flask import Flask, g, jsonify, request
from flask.views import MethodView
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from flask_smorest import Api, Blueprint
from marshmallow import Schema, fields, validate
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


# =============================================================================
# SECTION 1 — SETTINGS
# Read configuration from environment variables, initialise logging, and
# configure the database connection.
# =============================================================================

# -- Environment variables (with sensible defaults for local dev) --------------
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/practice"
)
SECRET_KEY: str     = os.getenv("SECRET_KEY",     "dev-secret-key-change-in-production")
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-change-in-production")
LOG_LEVEL: str      = os.getenv("LOG_LEVEL", "INFO").upper()
APP_ENV: str        = os.getenv("APP_ENV", "development")

# -- Logging initialisation ---------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.info("Starting Flask app in %s mode", APP_ENV)

# -- SQLAlchemy engine & session factory --------------------------------------
engine = create_engine(
    DATABASE_URL,
    echo=(APP_ENV == "development"),   # logs SQL in dev only
    echo_pool=False,
    pool_pre_ping=True,                # verify connections before use
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# =============================================================================
# SECTION 2 — MODELS
# Define the SQLAlchemy ORM models following the standard Flask pattern:
#   • A single DeclarativeBase subclass (Base) shared by all models.
#   • Each model lives in the same module; in larger apps split into models.py.
# =============================================================================

class PaymentMethod(str, enum.Enum):
    """Allowed payment methods for a Payslip."""
    cheque = "cheque"
    cash   = "cash"


class Base(DeclarativeBase):
    """Shared declarative base — adds audit timestamp columns to every model."""

    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Row creation timestamp (UTC)",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Last-modified timestamp (UTC)",
    )


class Department(Base):
    """Represents a company department."""

    __tablename__ = "department"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Primary key (UUID v4, auto-generated)",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True,
        comment="Unique department name",
    )

    # One department → many employees
    employees: Mapped[List["Employee"]] = relationship(
        "Employee", back_populates="department", lazy="select"
    )

    def to_dict(self) -> dict:
        def _dt(v):
            return v.isoformat() if isinstance(v, datetime) else v
        return {"id": str(self.id), "name": self.name,
                "created_at": _dt(self.created_at), "timestamp": _dt(self.timestamp)}

    def __repr__(self) -> str:
        return f"<Department id={self.id} name={self.name!r}>"


class Employee(Base):
    """Represents a company employee."""

    __tablename__ = "employee"
    __table_args__ = (
        CheckConstraint("salary > 0", name="ck_employee_salary_positive"),
        CheckConstraint(
            "total_work_hours >= 0 AND total_work_hours <= 24",
            name="ck_employee_work_hours_range",
        ),
        Index("ix_employee_book_list", "book_list", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Primary key (UUID v4, auto-generated)",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Full name of the employee"
    )
    date_of_birth: Mapped[date] = mapped_column(
        Date, nullable=False, comment="Date of birth"
    )
    salary: Mapped[float] = mapped_column(
        index=True, comment="Monthly salary (must be > 0)"
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("department.id", ondelete="RESTRICT", onupdate="CASCADE"),
        index=True, comment="FK to Department (UUID)",
    )
    total_work_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Daily work hours (0–24)"
    )
    book_list: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String), nullable=True, comment="Books written by the employee"
    )

    department: Mapped["Department"] = relationship(
        "Department", back_populates="employees"
    )
    payslips: Mapped[List["Payslip"]] = relationship(
        "Payslip", back_populates="employee", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Employee id={self.id} name={self.name!r}>"


class Payslip(Base):
    """Represents a payment record for an employee."""

    __tablename__ = "payslip"
    __table_args__ = (
        CheckConstraint("payment_amount > 0", name="ck_payslip_payment_amount_positive"),
        Index("ix_payslip_employee_id",   "employee_id"),
        Index("ix_payslip_payment_date",  "payment_date"),
        Index("ix_payslip_payment_method","payment_method"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Primary key (UUID v4, auto-generated)",
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False, comment="FK to Employee (UUID)",
    )
    payment_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="Date the payment was issued"
    )
    payment_amount: Mapped[float] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False, comment="Amount paid (> 0)"
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method_enum"),
        nullable=False, comment="Payment method: cheque or cash",
    )

    employee: Mapped["Employee"] = relationship("Employee", back_populates="payslips")

    def __repr__(self) -> str:
        return (f"<Payslip id={self.id} employee_id={self.employee_id} "
                f"amount={self.payment_amount} method={self.payment_method}>")


# -- Many-to-many association table: user ↔ role (no ORM class needed) --------
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    """RBAC role (e.g. admin, manager, viewer)."""

    __tablename__ = "role"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Primary key (UUID v4)",
    )
    name: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
        comment="Unique role name e.g. admin / manager / viewer",
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Human-readable description"
    )

    users: Mapped[List["User"]] = relationship(
        "User", secondary=user_roles, back_populates="roles"
    )

    def __repr__(self) -> str:
        return f"<Role name={self.name!r}>"


class User(Base):
    """Application user — holds credentials and is assigned one or more roles."""

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Primary key (UUID v4)",
    )
    username: Mapped[str] = mapped_column(
        String(150), nullable=False, unique=True, index=True,
        comment="Unique login username",
    )
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True,
        comment="Unique e-mail address",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt password hash"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="Account enabled flag"
    )

    roles: Mapped[List[Role]] = relationship(
        "Role", secondary=user_roles, back_populates="users"
    )

    # -- helpers --------------------------------------------------------------
    def set_password(self, plain: str) -> None:
        """Hash *plain* with bcrypt and store the result."""
        self.password_hash = bcrypt.hashpw(
            plain.encode(), bcrypt.gensalt()
        ).decode()

    def check_password(self, plain: str) -> bool:
        """Return True if *plain* matches the stored hash."""
        return bcrypt.checkpw(plain.encode(), self.password_hash.encode())

    def role_names(self) -> list[str]:
        return [r.name for r in self.roles]

    def __repr__(self) -> str:
        return f"<User username={self.username!r} roles={self.role_names()}>"


# =============================================================================
# SECTION 3 — FLASK APPLICATION & SWAGGER (flask-smorest / OpenAPI 3)
# =============================================================================

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    JWT_SECRET_KEY=JWT_SECRET_KEY,
    JWT_ACCESS_TOKEN_EXPIRES=False,   # long-lived for demo; use timedelta in prod
    # flask-smorest / OpenAPI settings
    API_TITLE="Flask Demo API",
    API_VERSION="v1",
    OPENAPI_VERSION="3.0.3",
    OPENAPI_URL_PREFIX="/",
    OPENAPI_SWAGGER_UI_PATH="/swagger",
    OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
)

jwt = JWTManager(app)   # Initialise flask-jwt-extended
api = Api(app)          # Initialise flask-smorest

# Register Bearer token security scheme so Swagger UI shows an Authorise button
api.spec.components.security_scheme(
    "BearerAuth",
    {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
)


# =============================================================================
# SECTION 4 — MIDDLEWARE
# Flask middleware is implemented via before_request / after_request hooks.
# Here we:
#   • Read a custom request header  (X-Request-ID) and store it in Flask's `g`.
#   • Inject a response header      (X-Processed-By) before the response leaves.
#   • Open / close a DB session per request and expose it via `g.db`.
# =============================================================================

@app.before_request
def open_db_session() -> None:
    """Open a SQLAlchemy session for the lifetime of the request."""
    g.db = SessionLocal()
    logger.debug("DB session opened for request %s", request.path)


@app.before_request
def read_request_headers() -> None:
    """
    Read custom HTTP request headers and attach them to Flask's `g` object
    so any view function can access them without re-reading the header dict.

    Demonstrates: reading headers → enriching request context.
    """
    # Read X-Request-ID (supplied by client / API gateway) or generate one
    g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    # Read an optional caller identity header
    g.caller     = request.headers.get("X-Caller", "anonymous")
    logger.info("Request [%s] from caller=%s  %s %s",
                g.request_id, g.caller, request.method, request.path)


@app.after_request
def add_response_headers(response):
    """
    Add custom headers to every outgoing HTTP response.

    Demonstrates: injecting data into the response before it reaches the client.
    """
    response.headers["X-Request-ID"]   = g.get("request_id", "unknown")
    response.headers["X-Processed-By"] = f"FlaskDemoAPI/{APP_ENV}"
    return response


@app.teardown_request
def close_db_session(exc: Optional[Exception]) -> None:
    """Close the DB session at the end of every request (even on errors)."""
    db: Optional[Session] = g.pop("db", None)
    if db is not None:
        if exc:
            db.rollback()
        db.close()
        logger.debug("DB session closed")


# =============================================================================
# SECTION 4b — RBAC HELPERS
# `roles_required(*roles)` is a decorator that:
#   1. Enforces a valid JWT (via @jwt_required).
#   2. Reads the `roles` claim embedded in the token.
#   3. Rejects the request with 403 if none of the required roles are present.
# =============================================================================

from functools import wraps


def roles_required(*required_roles: str):
    """
    Decorator factory — protect a view so only users whose JWT contains at
    least one of *required_roles* can access it.

    Usage::

        @jwt_required()
        @roles_required("admin", "manager")
        def my_view(): ...
    """
    def decorator(fn):
        @wraps(fn)
        @jwt_required()   # validates signature + expiry first
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            user_roles: list[str] = claims.get("roles", [])
            if not any(r in user_roles for r in required_roles):
                logger.warning(
                    "Access denied for user=%s  required=%s  has=%s",
                    get_jwt_identity(), required_roles, user_roles,
                )
                return jsonify(error="Forbidden: insufficient role"), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# SECTION 5 — MARSHMALLOW SCHEMAS (used by flask-smorest for validation + docs)
# =============================================================================

# Marshmallow 4 calls value.isoformat() as an unbound method; if the DB driver
# returns the timestamp as a string (server_default columns before full hydration)
# this raises a TypeError. FlexDateTime handles both cases gracefully.
class FlexDateTime(fields.DateTime):
    def _serialize(self, value, attr, obj, **kwargs):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return super()._serialize(value, attr, obj, **kwargs)

class DepartmentSchema(Schema):
    id         = fields.UUID(dump_only=True)
    name       = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    created_at = FlexDateTime(dump_only=True)
    timestamp  = FlexDateTime(dump_only=True)


class DepartmentQuerySchema(Schema):
    """Query-parameter schema — demonstrates query param parsing."""
    search   = fields.Str(load_default=None,  metadata={"description": "Filter departments by name (case-insensitive substring match)"})
    page     = fields.Int(load_default=1,     validate=validate.Range(min=1), metadata={"description": "Page number (1-based)"})
    per_page = fields.Int(load_default=10,    validate=validate.Range(min=1, max=100), metadata={"description": "Results per page"})


class RoleSchema(Schema):
    id          = fields.UUID(dump_only=True)
    name        = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    description = fields.Str(load_default=None)
    created_at  = FlexDateTime(dump_only=True)


class UserSchema(Schema):
    id         = fields.UUID(dump_only=True)
    username   = fields.Str(required=True, validate=validate.Length(min=3, max=150))
    email      = fields.Email(required=True)
    is_active  = fields.Bool(dump_only=True)
    roles      = fields.List(fields.Str(), dump_only=True)
    created_at = FlexDateTime(dump_only=True)


class RegisterSchema(Schema):
    """Input for POST /auth/register."""
    username = fields.Str(required=True, validate=validate.Length(min=3, max=150))
    email    = fields.Email(required=True)
    password = fields.Str(required=True, validate=validate.Length(min=8),
                          load_only=True, metadata={"format": "password"})


class LoginSchema(Schema):
    """Input for POST /auth/login."""
    username = fields.Str(required=True)
    password = fields.Str(required=True, load_only=True, metadata={"format": "password"})


class TokenSchema(Schema):
    """Returned on successful login."""
    access_token  = fields.Str()
    refresh_token = fields.Str()
    token_type    = fields.Str()


class AssignRoleSchema(Schema):
    """Input for POST /auth/users/<user_id>/roles."""
    role_name = fields.Str(required=True)


# =============================================================================
# SECTION 6 — VIEWS (async REST endpoints for the Department resource)
# Blueprint groups all /departments routes; registered on the Api instance.
# =============================================================================

# ── Auth blueprint ────────────────────────────────────────────────────────────
auth_blp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
    description="JWT authentication and RBAC user/role management",
)


@auth_blp.route("/register")
class AuthRegister(MethodView):

    @auth_blp.arguments(RegisterSchema)
    @auth_blp.response(201, UserSchema)
    def post(self, body: dict):
        """Register a new user account."""
        db: Session = g.db
        if db.query(User).filter_by(username=body["username"]).first():
            return jsonify(error="Username already taken"), 409
        if db.query(User).filter_by(email=body["email"]).first():
            return jsonify(error="E-mail already registered"), 409
        user = User(username=body["username"], email=body["email"])
        user.set_password(body["password"])
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("Registered user id=%s username=%s", user.id, user.username)
        return _user_to_schema(user)


@auth_blp.route("/login")
class AuthLogin(MethodView):

    @auth_blp.arguments(LoginSchema)
    @auth_blp.response(200, TokenSchema)
    def post(self, body: dict):
        """Authenticate and receive a JWT access + refresh token pair."""
        db: Session = g.db
        user = db.query(User).filter_by(username=body["username"]).first()
        if not user or not user.check_password(body["password"]):
            return jsonify(error="Invalid credentials"), 401
        if not user.is_active:
            return jsonify(error="Account disabled"), 403
        # Embed roles in the JWT as an additional claim for RBAC checks
        additional_claims = {"roles": user.role_names()}
        access  = create_access_token(identity=str(user.id),
                                      additional_claims=additional_claims)
        refresh = create_refresh_token(identity=str(user.id))
        logger.info("Login user id=%s roles=%s", user.id, user.role_names())
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


@auth_blp.route("/refresh")
class AuthRefresh(MethodView):

    @auth_blp.response(200, TokenSchema)
    @jwt_required(refresh=True)
    def post(self):
        """Exchange a refresh token for a new access token."""
        db: Session = g.db
        user_id = get_jwt_identity()
        user    = db.query(User).filter_by(id=user_id).first()
        if not user or not user.is_active:
            return jsonify(error="User not found or disabled"), 404
        additional_claims = {"roles": user.role_names()}
        access = create_access_token(identity=user_id,
                                     additional_claims=additional_claims)
        return {"access_token": access, "refresh_token": "", "token_type": "bearer"}


@auth_blp.route("/me")
class AuthMe(MethodView):

    @auth_blp.response(200, UserSchema)
    @jwt_required()
    def get(self):
        """Return the profile of the currently authenticated user."""
        db: Session = g.db
        user = db.query(User).filter_by(id=get_jwt_identity()).first()
        if not user:
            return jsonify(error="User not found"), 404
        return _user_to_schema(user)


# ── Role management (admin only) ──────────────────────────────────────────────

@auth_blp.route("/roles")
class RoleList(MethodView):

    @auth_blp.response(200, RoleSchema(many=True))
    @roles_required("admin")
    def get(self):
        """List all roles. **Requires: admin**"""
        return g.db.query(Role).all()

    @auth_blp.arguments(RoleSchema)
    @auth_blp.response(201, RoleSchema)
    @roles_required("admin")
    def post(self, body: dict):
        """Create a new role. **Requires: admin**"""
        db: Session = g.db
        if db.query(Role).filter_by(name=body["name"]).first():
            return jsonify(error="Role already exists"), 409
        role = Role(name=body["name"], description=body.get("description"))
        db.add(role)
        db.commit()
        db.refresh(role)
        return role


@auth_blp.route("/users")
class UserList(MethodView):

    @auth_blp.response(200, UserSchema(many=True))
    @roles_required("admin")
    def get(self):
        """List all users. **Requires: admin**"""
        users = g.db.query(User).all()
        return [_user_to_schema(u) for u in users]


@auth_blp.route("/users/<uuid:user_id>/roles")
class UserRoleAssignment(MethodView):

    @auth_blp.arguments(AssignRoleSchema)
    @auth_blp.response(200, UserSchema)
    @roles_required("admin")
    def post(self, body: dict, user_id: uuid.UUID):
        """Assign a role to a user. **Requires: admin**"""
        db: Session = g.db
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify(error="User not found"), 404
        role = db.query(Role).filter_by(name=body["role_name"]).first()
        if not role:
            return jsonify(error="Role not found"), 404
        if role not in user.roles:
            user.roles.append(role)
            db.commit()
            db.refresh(user)
        return _user_to_schema(user)

    @auth_blp.arguments(AssignRoleSchema)
    @auth_blp.response(200, UserSchema)
    @roles_required("admin")
    def delete(self, body: dict, user_id: uuid.UUID):
        """Remove a role from a user. **Requires: admin**"""
        db: Session = g.db
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify(error="User not found"), 404
        role = db.query(Role).filter_by(name=body["role_name"]).first()
        if role and role in user.roles:
            user.roles.remove(role)
            db.commit()
            db.refresh(user)
        return _user_to_schema(user)


# ── Helper: serialise User ORM object to dict expected by UserSchema ----------
def _user_to_schema(user: User) -> dict:
    return {
        "id":         user.id,
        "username":   user.username,
        "email":      user.email,
        "is_active":  user.is_active,
        "roles":      user.role_names(),
        "created_at": user.created_at,
    }


# ── Department blueprint (protected) ─────────────────────────────────────────
dept_blp = Blueprint(
    "departments",
    __name__,
    url_prefix="/departments",
    description="CRUD operations for the Department resource",
)


# ── GET /departments  (list with optional search + pagination) ────────────────
@dept_blp.route("/")
class DepartmentList(MethodView):

    @dept_blp.arguments(DepartmentQuerySchema, location="query")
    @dept_blp.response(200, DepartmentSchema(many=True))
    @dept_blp.doc(security=[{"BearerAuth": []}])
    @roles_required("admin", "manager", "viewer")
    def get(self, query_args: dict):
        """
        List departments. **Requires: admin | manager | viewer**

        Demonstrates **query parameters**: `search`, `page`, `per_page`.
        """
        db: Session = g.db
        q = db.query(Department)

        if query_args.get("search"):
            q = q.filter(Department.name.ilike(f"%{query_args['search']}%"))

        total = q.count()
        offset = (query_args["page"] - 1) * query_args["per_page"]
        departments = q.offset(offset).limit(query_args["per_page"]).all()

        logger.info("Listed %d/%d departments (page=%d)", len(departments), total,
                    query_args["page"])
        return DepartmentSchema(many=True).dump(departments)

    @dept_blp.arguments(DepartmentSchema)
    @dept_blp.response(201, DepartmentSchema)
    @dept_blp.doc(security=[{"BearerAuth": []}])
    @roles_required("admin", "manager")
    def post(self, new_data: dict):
        """Create a new department. **Requires: admin | manager**"""
        db: Session = g.db
        dept = Department(name=new_data["name"])
        db.add(dept)
        db.commit()
        db.refresh(dept)
        logger.info("Created department id=%s name=%s", dept.id, dept.name)
        return DepartmentSchema().dump(dept)


# ── /departments/<dept_id>  (item-level operations) ──────────────────────────
@dept_blp.route("/<uuid:dept_id>")
class DepartmentItem(MethodView):
    """
    Demonstrates **path parameters**: `dept_id` (UUID) is part of the URL.
    """

    @dept_blp.response(200, DepartmentSchema)
    @dept_blp.doc(security=[{"BearerAuth": []}])
    @roles_required("admin", "manager", "viewer")
    def get(self, dept_id: uuid.UUID):
        """Retrieve a single department by ID. **Requires: admin | manager | viewer**"""
        db: Session = g.db
        dept = db.query(Department).filter_by(id=dept_id).first()
        if dept is None:
            return jsonify(error="Department not found"), 404
        return DepartmentSchema().dump(dept)

    @dept_blp.arguments(DepartmentSchema(partial=True))
    @dept_blp.response(200, DepartmentSchema)
    @dept_blp.doc(security=[{"BearerAuth": []}])
    @roles_required("admin", "manager")
    def patch(self, update_data: dict, dept_id: uuid.UUID):
        """Partially update a department. **Requires: admin | manager**"""
        db: Session = g.db
        dept = db.query(Department).filter_by(id=dept_id).first()
        if dept is None:
            return jsonify(error="Department not found"), 404
        for field, value in update_data.items():
            setattr(dept, field, value)
        db.commit()
        db.refresh(dept)
        logger.info("Updated department id=%s", dept.id)
        return DepartmentSchema().dump(dept)

    @dept_blp.response(204)
    @dept_blp.doc(security=[{"BearerAuth": []}])
    @roles_required("admin")
    def delete(self, dept_id: uuid.UUID):
        """Delete a department. **Requires: admin**"""
        db: Session = g.db
        dept = db.query(Department).filter_by(id=dept_id).first()
        if dept is None:
            return jsonify(error="Department not found"), 404
        db.delete(dept)
        db.commit()
        logger.info("Deleted department id=%s", dept_id)


# =============================================================================
# SECTION 7 — ROUTES
# Register the blueprint (and its URL rules) on the Api instance.
# =============================================================================

api.register_blueprint(auth_blp)
api.register_blueprint(dept_blp)

# Route summary:
#   POST   /auth/register                        — register new user
#   POST   /auth/login                           — login → JWT tokens
#   POST   /auth/refresh                         — refresh access token
#   GET    /auth/me                              — current user profile  [jwt]
#   GET    /auth/roles                           — list roles            [admin]
#   POST   /auth/roles                           — create role           [admin]
#   GET    /auth/users                           — list users            [admin]
#   POST   /auth/users/<user_id>/roles           — assign role           [admin]
#   DELETE /auth/users/<user_id>/roles           — revoke role           [admin]
#   GET    /departments/                         — list  (search/page)   [any role]
#   POST   /departments/                         — create                [admin|manager]
#   GET    /departments/<dept_id>                — get by ID             [any role]
#   PATCH  /departments/<dept_id>                — partial update        [admin|manager]
#   DELETE /departments/<dept_id>                — delete                [admin]
#   GET    /swagger                              — Swagger UI
#   GET    /openapi.json                         — OpenAPI spec


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Create tables if they do not exist yet (idempotent)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured.")
    logger.info("Swagger UI available at http://127.0.0.1:5000/swagger")
    app.run(debug=(APP_ENV == "development"), host="0.0.0.0", port=5000)
