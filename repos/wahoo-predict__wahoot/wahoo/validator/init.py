import argparse
import os
import sys
import subprocess
import sqlite3
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv


def check_virtual_env() -> Optional[Path]:
    venv_path = os.environ.get("VIRTUAL_ENV")
    if venv_path:
        return Path(venv_path)

    cwd = Path.cwd()
    for venv_name in ["venv", "env", ".venv", ".env"]:
        venv_dir = cwd / venv_name
        if venv_dir.exists() and (venv_dir / "bin" / "python").exists():
            return venv_dir

    return None


def check_dependencies() -> bool:
    required_packages = {
        "bittensor": "bittensor",
        "httpx": "httpx",
        "torch": "torch",
        "sqlalchemy": "sqlalchemy",
        "alembic": "alembic",
        "python-dotenv": "dotenv",
        "pandas": "pandas",
        "numpy": "numpy",
    }
    missing = []
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package_name)

    if not missing:
        return True

    print(f"Missing dependencies: {', '.join(missing)}")
    return False


def check_uv_available() -> bool:
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install_dependencies(venv_path: Optional[Path] = None) -> bool:
    print("Attempting to install missing dependencies...")

    use_uv = check_uv_available()

    project_root = Path(__file__).parent.parent.parent
    pyproject_file = project_root / "pyproject.toml"
    requirements_file = project_root / "requirements.txt"

    is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False

    if use_uv:
        print("Using uv for dependency installation...")
        try:
            if venv_path:
                python_exe = str(venv_path / "bin" / "python")
                cmd = ["uv", "pip", "install", "--python", python_exe]
            else:
                cmd = ["uv", "pip", "install"]

            if pyproject_file.exists():
                cmd.extend(["-e", "."])
            elif requirements_file.exists():
                cmd.extend(["-r", str(requirements_file)])
            else:
                print("ERROR: Neither pyproject.toml nor requirements.txt found")
                return False

            print(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr)
            return True
        except subprocess.CalledProcessError as e:
            print("ERROR: Failed to install dependencies with uv:")
            print(e.stderr)
            print("\nFalling back to pip...")
            use_uv = False

    if not use_uv:
        print("Using pip for dependency installation...")

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--user",
                    "--dry-run",
                    "requests",
                ],
                capture_output=True,
                timeout=5,
            )
            needs_sudo = False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            needs_sudo = True

        if needs_sudo and not is_root:
            print("\n" + "=" * 70)
            print(
                "ERROR: Missing dependencies require installation with elevated privileges."
            )
            print("Please run one of the following:")
            if pyproject_file.exists():
                print(
                    "  1. Activate your virtual environment and run: uv pip install -e ."
                )
                print("  2. Or with pip: pip install -e .")
            else:
                print(
                    "  1. Activate your virtual environment and run: pip install -r requirements.txt"
                )
            print("  2. Run as root/admin: sudo python {' '.join(sys.argv)}")
            print("=" * 70)
            return False

        if not pyproject_file.exists() and not requirements_file.exists():
            print("ERROR: Neither pyproject.toml nor requirements.txt found")
            return False

        try:
            if pyproject_file.exists():
                cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
            else:
                cmd = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements_file),
                ]

            if not is_root and not venv_path:
                cmd.append("--user")

            print(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print("ERROR: Failed to install dependencies:")
            print(e.stderr)
            return False

    return False


def check_sqlite() -> bool:
    try:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("SELECT sqlite_version()")
        version = cursor.fetchone()[0]
        conn.close()
        print(f"SQLite version: {version}")
        return True
    except Exception as e:
        print(f"ERROR: SQLite check failed: {e}")
        return False


def get_db_path() -> Path:
    db_path = os.getenv("VALIDATOR_DB_PATH", "validator.db")
    if not os.path.isabs(db_path):
        project_root = Path(__file__).parent.parent.parent
        db_path = project_root / db_path
    return Path(db_path)


def check_database_exists(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1")
        conn.close()
        return True
    except sqlite3.Error:
        return False


def create_database(db_path: Path) -> bool:
    print(f"Creating database at {db_path}...")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_file = Path(__file__).parent / "database" / "schema.sql"
    if not schema_file.exists():
        print(f"ERROR: Schema file not found at {schema_file}")
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        with open(schema_file, "r") as f:
            schema_sql = f.read()

        conn.executescript(schema_sql)
        conn.close()
        print(f"Database created successfully at {db_path}")
        return True
    except Exception as e:
        print(f"ERROR: Failed to create database: {e}")
        return False


def check_alembic_head() -> Tuple[bool, Optional[str]]:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        alembic_dir = Path(__file__).parent / "database" / "alembic"
        alembic_ini = Path(__file__).parent / "database" / "alembic.ini"

        if not alembic_ini.exists():
            return False, "alembic.ini not found"

        original_cwd = os.getcwd()
        os.chdir(alembic_dir.parent)

        try:
            alembic_cfg = Config(str(alembic_ini))
            script = ScriptDirectory.from_config(alembic_cfg)

            try:
                from alembic.runtime.migration import MigrationContext
                from sqlalchemy import create_engine

                db_path = get_db_path()
                engine = create_engine(f"sqlite:///{db_path}")
                with engine.connect() as conn:
                    context = MigrationContext.configure(conn)
                    current_rev = context.get_current_revision()
            except Exception:
                current_rev = None

            head_rev = script.get_current_head()

            if head_rev is None:
                return True, None

            if current_rev == head_rev:
                return True, None
            elif current_rev is None:
                return False, "Database not initialized with Alembic"
            else:
                return False, f"Database at {current_rev}, head is {head_rev}"
        finally:
            os.chdir(original_cwd)
    except ImportError:
        return False, "Alembic not installed"
    except Exception as e:
        return False, f"Error checking Alembic: {e}"


def upgrade_database() -> bool:
    try:
        from alembic.config import Config
        from alembic import command

        alembic_ini = Path(__file__).parent / "database" / "alembic.ini"
        alembic_dir = Path(__file__).parent / "database" / "alembic"

        if not alembic_ini.exists():
            print("ERROR: alembic.ini not found")
            return False

        original_cwd = os.getcwd()
        os.chdir(alembic_dir.parent)

        try:
            alembic_cfg = Config(str(alembic_ini))
            from alembic.script import ScriptDirectory

            script = ScriptDirectory.from_config(alembic_cfg)
            head_rev = script.get_current_head()

            if head_rev is None:
                print(
                    "No Alembic migrations found. Database initialized with schema.sql"
                )
                print(
                    "To create migrations, run: alembic revision --autogenerate -m 'Initial migration'"
                )
                return True

            print("Upgrading database to head...")
            command.upgrade(alembic_cfg, "head")
            print("Database upgraded successfully")
            return True
        finally:
            os.chdir(original_cwd)
    except Exception as e:
        print(f"ERROR: Failed to upgrade database: {e}")
        return False


def load_config() -> dict:
    config = {}

    if load_dotenv:
        project_root = Path(__file__).parent.parent.parent
        env_file = project_root / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            print(f"Loaded environment variables from {env_file}")

    config["VALIDATOR_DB_PATH"] = os.getenv("VALIDATOR_DB_PATH", "validator.db")

    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize validator environment and database"
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip dependency checking",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database initialization",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="Override database path (default: validator.db or VALIDATOR_DB_PATH env var)",
    )
    return parser.parse_args()


def initialize(
    skip_deps: bool = False,
    skip_db: bool = False,
    db_path: Optional[str] = None,
) -> int:
    if db_path:
        os.environ["VALIDATOR_DB_PATH"] = db_path

    print("=" * 70)
    print("Validator Initialization")
    print("=" * 70)

    config = load_config()
    if db_path:
        config["VALIDATOR_DB_PATH"] = db_path

    if not skip_deps:
        print("\n[1/4] Checking dependencies...")
        venv_path = check_virtual_env()
        if venv_path:
            print(f"Virtual environment detected: {venv_path}")

        if not check_dependencies():
            if not install_dependencies(venv_path):
                return 1
            if not check_dependencies():
                print("ERROR: Dependencies still missing after installation attempt")
                return 1
        print("✓ All dependencies installed")
    else:
        print("\n[1/4] Skipping dependency check")

    print("\n[2/4] Checking SQLite...")
    if not check_sqlite():
        print("ERROR: SQLite check failed")
        return 1
    print("✓ SQLite available")

    if not skip_db:
        print("\n[3/4] Checking database...")
        db_path_obj = get_db_path()

        if not check_database_exists(db_path_obj):
            print(f"Database not found at {db_path_obj}")
            if not create_database(db_path_obj):
                return 1

        is_at_head, message = check_alembic_head()
        if not is_at_head:
            if message:
                print(f"Database migration needed: {message}")
            if not upgrade_database():
                return 1
        else:
            print("✓ Database is at Alembic head")
    else:
        print("\n[3/4] Skipping database check")

    print("\n[4/4] Final checks...")
    print(f"✓ Database path: {get_db_path()}")
    print("✓ Configuration loaded")

    print("\nInitialization complete!")

    return 0


def main() -> int:
    args = parse_args()

    return initialize(
        skip_deps=args.skip_deps,
        skip_db=args.skip_db,
        db_path=args.db_path,
    )


if __name__ == "__main__":
    sys.exit(main())
