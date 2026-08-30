# encoding: utf-8
from contextlib import contextmanager
from typing import Optional, Generator, Iterable, Union

from ckan.plugins import PluginImplementations, toolkit
from ckanext.datastore.interfaces import IDatastore
from sqlalchemy import create_engine, sql, text
from sqlalchemy.engine import Connection, Engine, Row
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import TextClause

_read_engine = None
_write_engine = None


def get_engine(write: bool = False) -> Engine:
    """

    :param write:  (Default value = False)

    """
    if write:
        global _write_engine
        if _write_engine is None:
            # Write engine doesn't really need to keep connections open, as it happens
            #  quite rarely.
            _write_engine = create_engine(
                toolkit.config["ckan.datastore.write_url"], poolclass=NullPool
            )
        return _write_engine
    else:
        global _read_engine
        if _read_engine is None:
            _read_engine = create_engine(toolkit.config["ckan.datastore.read_url"])
        return _read_engine


@contextmanager
def get_connection(
    connection: Optional[Connection] = None,
    write: bool = False,
    raw: bool = False,
) -> Generator[Connection, None, None]:
    """Context manager to get a database connection

    This will either return the provided connection (and then leave it open)
    or create a new connection for this operation only.

    :param connection: Database connection or None (Default value = None)
    :param write: If connection is None, specify whether to get a read-only
        or a read-write connection (Default value = False)
    :param raw: If connection is None, specify whether to get a raw
        connection (Default value = False)
    """
    if connection:
        yield connection
    else:
        engine = get_engine(write=write)
        with engine.begin() as new_connection:
            if raw:
                yield new_connection.connection
            else:
                yield new_connection


def _index_name(table: str, field: str, index_type: str) -> str:
    """Get the name of an index from a table, field and index type

    :param table: Table name
    :param field: Field name
    :param index_type: Index type
    :returns:  The index name
    """
    return f"{table}_{field}_{index_type}"


def create_index(
    connection: Connection,
    table: str,
    field: str,
    index_type: str = "GIST",
):
    """Create an index on a field

    :param connection: Database connection
    :param table: Table name
    :param field: Field name
    :param index_type: Index type (Default value = 'GIST')
    """
    index_name: str = _index_name(table, field, index_type)
    s: TextClause = text(
        f"""
      CREATE INDEX IF NOT EXISTS "{index_name}"
          ON "{table}"
       USING {index_type}("{field}")
       WHERE "{field}" IS NOT NULL;
       """
    )
    connection.execute(s)


def index_exists(
    connection: Connection,
    table: str,
    field: str,
    index_type: str = "GIST",
) -> bool:
    """Test if an index exists

    Note this will look for index named as per _index_name

    :param connection: Database connection
    :param table: Table name
    :param field: Field name
    :param index_type: Index type (Default value = u'GIST')
    :returns: True if the index exists, False otherwise.
    """
    indexes_table = sql.table("pg_indexes")

    query: Select = (
        sql.select([sql.func.count()])
        .select_from(indexes_table)
        .where("indexname" == _index_name(table, field, index_type))
    )

    result = connection.execute(query).fetchone()
    return result[0] > 0


def fields_exist(
    connection: Connection,
    table: str,
    fields: list[str],
) -> bool:
    """Test if the all the given fields exist

    :param connection: Database connection
    :param table: Table to test
    :param fields: List of fields to look for
    :returns: True if all the fields exist, false if not
    """
    query: Select = sql.select("*", from_obj=sql.table(table)).limit(0)
    all_fields = connection.execute(query).keys()
    for field in fields:
        if field not in all_fields:
            return False
    return True


def create_geom_column(
    connection: Connection,
    table: str,
    field: str,
    geom_type: str,
    srid: Union[str, int],
) -> None:
    """Create a geospatial column on the given table

    :param connection: The database connection
    :param table: The table to create column on
    :param field: The name of the geom column to be created
    :param srid: The projection of the geom column
    :param geom_type: The type of geometry column to add.
    """
    query: TextClause = sql.text(
        f"""ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{field}" geometry({geom_type}, {srid});"""
    )
    connection.execute(query)


def invoke_search_plugins(data_dict: dict, field_types: dict[str, str]):
    """Invoke IDatastore plugins datastore_search

    This is for the specific uses of this plugin, and this function only
    returns a subset of the information generated by the plugins.

    :param data_dict: The datastore_search request
    :param field_types: The field types, as a dict of field name to type name
    :returns: A tuple defining (
            SQL 'from' statement for full text queries,
            where clause,
            list of replacement values
        )
    """
    query_dict = {"select": [], "sort": [], "where": []}
    for plugin in PluginImplementations(IDatastore):
        query_dict = plugin.datastore_search({}, data_dict, field_types, query_dict)
    clauses = []
    values = []
    for clause_and_values in query_dict["where"]:
        clauses.append("(" + clause_and_values[0] + ")")
        values += clause_and_values[1:]

    where_clause = " AND ".join(clauses)
    if where_clause:
        where_clause = "WHERE " + where_clause

    if "ts_query" in query_dict and query_dict["ts_query"]:
        ts_query = query_dict["ts_query"]
    else:
        ts_query = ""

    return ts_query, where_clause, values


def get_field_values(
    connection: Connection,
    resource_id: str,
    field: str,
    is_bytes: bool = False
) -> list[str | bytes]:
    """Get a list of distinct values within a datastore field.

    :param connection: database connection
    :param resource_id: resource ID/ table name to query
    :param field: field name to query
    :returns: a list of distinct values
    """
    query: TextClause = text(f"""SELECT "{field}" FROM "{resource_id}";""")
    results: Iterable[Row] = connection.execute(query).fetchall()
    if is_bytes is True:
        return [bytes(item[0]) for item in results]
    return [item[0] for item in results]
