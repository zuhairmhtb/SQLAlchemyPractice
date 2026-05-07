# Database - SQLAlchemy

This repository demonstrates the different features of SQLAlchemy and relational database. Please view the file SQLAlchemy.html to view the notebook in browser.

To run the notebook, you need:
- Docker
- python 3.13
- uv package manager

## Imports

```python
import enum
import uuid
from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import (
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import logging
import time
from typing import Literal
from sqlalchemy import event
from sqlalchemy import asc, desc, distinct
from sqlalchemy.orm import Session, sessionmaker
import datetime
from sqlalchemy import and_, not_, or_
from sqlalchemy import column, literal_column
from sqlalchemy.sql import over
from sqlalchemy.sql.expression import over as sa_over
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm import selectinload
import contextlib
from sqlalchemy import delete as sa_delete
from sqlalchemy import insert as sa_insert
from sqlalchemy.exc import IntegrityError
import threading
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, event, pool
from collections import Counter
from sqlalchemy.exc import OperationalError
from sqlalchemy import update as sa_update
from sqlalchemy.orm.exc import StaleDataError
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Generic, List, Optional, Type, TypeVar
from sqlalchemy.orm import Session
```

### main.py

```python
import enum
import logging
import os
import uuid
from datetime import date, datetime
from typing import List, Optional
from functools import wraps
import bcrypt
from flask import Flask, g, jsonify, request
from flask_caching import Cache
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
```