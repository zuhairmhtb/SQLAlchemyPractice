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
from flask import Flask, g, jsonify, request
from flask.views import MethodView
from flask_smorest import Api, Blueprint
from marshmallow import Schema, fields, validate
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
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
SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
APP_ENV: str = os.getenv("APP_ENV", "development")

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
        return {"id": str(self.id), "name": self.name,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None}

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


# =============================================================================
# SECTION 3 — FLASK APPLICATION & SWAGGER (flask-smorest / OpenAPI 3)
# =============================================================================

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    # flask-smorest / OpenAPI settings
    API_TITLE="Flask Demo API",
    API_VERSION="v1",
    OPENAPI_VERSION="3.0.3",
    OPENAPI_URL_PREFIX="/",
    OPENAPI_SWAGGER_UI_PATH="/swagger",                           # Swagger UI at /swagger
    OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
)

api = Api(app)   # Initialise flask-smorest


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
# SECTION 5 — MARSHMALLOW SCHEMAS (used by flask-smorest for validation + docs)
# =============================================================================

class DepartmentSchema(Schema):
    id         = fields.UUID(dump_only=True)
    name       = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    created_at = fields.DateTime(dump_only=True)
    timestamp  = fields.DateTime(dump_only=True)


class DepartmentQuerySchema(Schema):
    """Query-parameter schema — demonstrates query param parsing."""
    search   = fields.Str(load_default=None,  metadata={"description": "Filter departments by name (case-insensitive substring match)"})
    page     = fields.Int(load_default=1,     validate=validate.Range(min=1), metadata={"description": "Page number (1-based)"})
    per_page = fields.Int(load_default=10,    validate=validate.Range(min=1, max=100), metadata={"description": "Results per page"})


# =============================================================================
# SECTION 6 — VIEWS (async REST endpoints for the Department resource)
# Blueprint groups all /departments routes; registered on the Api instance.
# =============================================================================

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
    async def get(self, query_args: dict):
        """
        List departments.

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
        return departments

    @dept_blp.arguments(DepartmentSchema)
    @dept_blp.response(201, DepartmentSchema)
    async def post(self, new_data: dict):
        """Create a new department."""
        db: Session = g.db
        dept = Department(name=new_data["name"])
        db.add(dept)
        db.commit()
        db.refresh(dept)
        logger.info("Created department id=%s name=%s", dept.id, dept.name)
        return dept


# ── /departments/<dept_id>  (item-level operations) ──────────────────────────
@dept_blp.route("/<uuid:dept_id>")
class DepartmentItem(MethodView):
    """
    Demonstrates **path parameters**: `dept_id` (UUID) is part of the URL.
    """

    @dept_blp.response(200, DepartmentSchema)
    async def get(self, dept_id: uuid.UUID):
        """Retrieve a single department by ID."""
        db: Session = g.db
        dept = db.query(Department).filter_by(id=dept_id).first()
        if dept is None:
            return jsonify(error="Department not found"), 404
        return dept

    @dept_blp.arguments(DepartmentSchema(partial=True))
    @dept_blp.response(200, DepartmentSchema)
    async def patch(self, update_data: dict, dept_id: uuid.UUID):
        """Partially update a department."""
        db: Session = g.db
        dept = db.query(Department).filter_by(id=dept_id).first()
        if dept is None:
            return jsonify(error="Department not found"), 404
        for field, value in update_data.items():
            setattr(dept, field, value)
        db.commit()
        db.refresh(dept)
        logger.info("Updated department id=%s", dept.id)
        return dept

    @dept_blp.response(204)
    async def delete(self, dept_id: uuid.UUID):
        """Delete a department."""
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

api.register_blueprint(dept_blp)

# Route summary (printed at startup for visibility):
#   GET    /departments/              — list  (query params: search, page, per_page)
#   POST   /departments/              — create
#   GET    /departments/<dept_id>     — get by ID  (path param: dept_id)
#   PATCH  /departments/<dept_id>     — partial update
#   DELETE /departments/<dept_id>     — delete
#   GET    /swagger                   — Swagger UI
#   GET    /openapi.json              — OpenAPI spec


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Create tables if they do not exist yet (idempotent)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured.")
    logger.info("Swagger UI available at http://127.0.0.1:5000/swagger")
    app.run(debug=(APP_ENV == "development"), host="0.0.0.0", port=5000)
