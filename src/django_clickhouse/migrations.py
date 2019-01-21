"""
Migrating database
"""
import datetime
from typing import Optional, Set

from django.db import DEFAULT_DB_ALIAS as DJANGO_DEFAULT_DB_ALIAS
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from infi.clickhouse_orm.database import ServerError, DatabaseException
from infi.clickhouse_orm.migrations import *
from infi.clickhouse_orm.utils import import_submodules

from .clickhouse_models import ClickHouseModel
from .configuration import config
from .database import connections, Database
from .utils import lazy_class_import, module_exists


class Migration:
    """
    Base class for migrations
    """
    operations = []

    def apply(self, db_alias, database=None):  # type: (str, Optional[Database]) -> None
        """
        Applies migration to given database
        :param db_alias: Database alias to apply migration to
        :param database: Sometimes I want to pass db object directly for testing purposes
        :return: None
        """
        db_router = lazy_class_import(config.DATABASE_ROUTER)()
        database = database or connections[db_alias]

        for op in self.operations:
            model_class = getattr(op, 'model_class', None)
            hints = getattr(op, 'hints', {})

            if db_router.allow_migrate(db_alias, self.__module__, op, model=model_class, **hints):
                op.apply(database)


def migrate_app(app_label, db_alias, up_to=9999, database=None):
    # type: (str, str, int, Optional[Database]) -> None
    """
    Migrates given django app
    :param app_label: App label to migrate
    :param db_alias: Database alias to migrate
    :param up_to: Migration number to migrate to
    :param database: Sometimes I want to pass db object directly for testing purposes
    :return: None
    """
    # Can't migrate such connection, just skip it
    if config.DATABASES[db_alias].get('readonly', False):
        return

    # Ignore force not migrated databases
    if not config.DATABASES[db_alias].get('migrate', True):
        return

    migrations_package = "%s.%s" % (app_label, config.MIGRATIONS_PACKAGE)

    if module_exists(migrations_package):
        database = database or connections[db_alias]
        migration_history_model = lazy_class_import(config.MIGRATION_HISTORY_MODEL)

        applied_migrations = migration_history_model.get_applied_migrations(db_alias, migrations_package)
        modules = import_submodules(migrations_package)
        unapplied_migrations = set(modules.keys()) - applied_migrations

        for name in sorted(unapplied_migrations):
            print('Applying ClickHouse migration %s for app %s in database %s' % (name, app_label, db_alias))
            migration = modules[name].Migration()
            migration.apply(db_alias, database=database)

            migration_history_model.set_migration_applied(db_alias, migrations_package, name)

            if int(name[:4]) >= up_to:
                break


@receiver(post_migrate)
def clickhouse_migrate(sender, **kwargs):
    if not config.MIGRATE_WITH_DEFAULT_DB:
        # If auto migration is enabled
        return

    if kwargs.get('using', DJANGO_DEFAULT_DB_ALIAS) != DJANGO_DEFAULT_DB_ALIAS:
        # Не надо выполнять синхронизацию для каждого шарда. Только один раз.
        return

    app_name = kwargs['app_config'].name

    for db_alias in config.DATABASES:
        migrate_app(app_name, db_alias)


class MigrationHistory(ClickHouseModel):
    """
    A model for storing which migrations were already applied to database.
    This
    """

    db_alias = StringField()
    package_name = StringField()
    module_name = StringField()
    applied = DateField()

    engine = MergeTree('applied', ('db_alias', 'package_name', 'module_name'))

    @classmethod
    def set_migration_applied(cls, db_alias, migrations_package, name):  # type: (str, str, str) -> None
        """
        Sets migration apply status
        :param db_alias: Database alias migration is applied to
        :param migrations_package: Package migration is stored in
        :param name: Migration name
        :return: None
        """
        # Ensure that table for migration storing is created
        for db_alias in cls.migrate_non_replicated_db_aliases:
            connections[db_alias].create_table(cls)

        cls.objects.bulk_create([
            cls(db_alias=db_alias, package_name=migrations_package, module_name=name, applied=datetime.date.today())
        ])

    @classmethod
    def get_applied_migrations(cls, db_alias, migrations_package):  # type: (str, str) -> Set[str]
        """
        Returns applied migrations names
        :param db_alias: Database alias, to check
        :param migrations_package: Package name to check
        :return: Set of migration names
        """
        qs = cls.objects.filter(package_name=migrations_package, db_alias=db_alias).only('module_name')
        try:
            return set(obj.module_name for obj in qs)
        except ServerError as ex:
            # Database doesn't exist or table doesn't exist
            if ex.code in {81, 60}:
                return set()
            raise ex
        except DatabaseException as ex:
            # If database doesn't exist no migrations are applied
            # This prevents readonly=True + db_exists=False infi exception
            if str(ex) == 'Database does not exist, and cannot be created under readonly connection':
                return set()
            raise ex

    @classmethod
    def table_name(cls):
        return 'django_clickhouse_migrations'
