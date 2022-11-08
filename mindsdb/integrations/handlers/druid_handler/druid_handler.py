from typing import Optional
from collections import OrderedDict

import pandas as pd
from pydruid.db import connect

from mindsdb_sql import parse_sql
from mindsdb_sql.render.sqlalchemy_render import SqlalchemyRender
from mindsdb.integrations.libs.base import DatabaseHandler
from pydruid.db.sqlalchemy import DruidDialect

from mindsdb_sql.parser.ast.base import ASTNode

from mindsdb.utilities import log
from mindsdb.integrations.libs.response import (
    HandlerStatusResponse as StatusResponse,
    HandlerResponse as Response,
    RESPONSE_TYPE
)
from mindsdb.integrations.libs.const import HANDLER_CONNECTION_ARG_TYPE as ARG_TYPE


class DruidHandler(DatabaseHandler):
    """
    This handler handles connection and execution of the Apache Druid statements.
    """

    name = 'druid'

    def __init__(self, name: str, connection_data: Optional[dict], **kwargs):
        """
        Initialize the handler.
        Args:
            name (str): name of particular handler instance
            connection_data (dict): parameters for connecting to the database
            **kwargs: arbitrary keyword arguments.
        """
        super().__init__(name)
        self.parser = parse_sql
        self.dialect = 'druid'

        optional_parameters = ['user', 'password']
        for parameter in optional_parameters:
            if parameter not in connection_data:
                connection_data[parameter] = None

        if 'path' not in connection_data:
            connection_data['path'] = '/druid/v2/sql/'

        if 'scheme' not in connection_data:
            connection_data['scheme'] = 'http'

        self.connection_data = connection_data
        self.kwargs = kwargs

        self.connection = None
        self.is_connected = False

    def __del__(self):
        if self.is_connected is True:
            self.disconnect()

    def connect(self) -> StatusResponse:
        """
        Set up the connection required by the handler.
        Returns:
            HandlerStatusResponse
        """

        if self.is_connected is True:
            return self.connection

        self.connection = connect(
            host=self.connection_data['host'],
            port=self.connection_data['port'],
            path=self.connection_data['path'],
            scheme=self.connection_data['scheme'],
            user=self.connection_data['user'],
            password=self.connection_data['password']
        )
        self.is_connected = True

        return self.connection

    def disconnect(self):
        """
        Close any existing connections.
        """

        if self.is_connected is False:
            return

        self.connection.close()
        self.is_connected = False
        return self.is_connected

    def check_connection(self) -> StatusResponse:
        """
        Check connection to the handler.
        Returns:
            HandlerStatusResponse
        """

        response = StatusResponse(False)
        need_to_close = self.is_connected is False

        try:
            self.connect()
            response.success = True
        except Exception as e:
            log.logger.error(f'Error connecting to Pinot, {e}!')
            response.error_message = str(e)
        finally:
            if response.success is True and need_to_close:
                self.disconnect()
            if response.success is False and self.is_connected is True:
                self.is_connected = False

        return response

    def native_query(self, query: str) -> StatusResponse:
        """
        Receive raw query and act upon it somehow.
        Args:
            query (str): query in native format
        Returns:
            HandlerResponse
        """

        need_to_close = self.is_connected is False

        connection = self.connect()
        cursor = connection.cursor()

        try:
            cursor.execute(query)
            result = cursor.fetchall()
            if result:
                response = Response(
                    RESPONSE_TYPE.TABLE,
                    data_frame=pd.DataFrame(
                        result,
                        columns=[x[0] for x in cursor.description]
                    )
                )
            else:
                connection.commit()
                response = Response(RESPONSE_TYPE.OK)
        except Exception as e:
            log.logger.error(f'Error running query: {query} on Pinot!')
            response = Response(
                RESPONSE_TYPE.ERROR,
                error_message=str(e)
            )

        cursor.close()
        if need_to_close is True:
            self.disconnect()

        return response

    def query(self, query: ASTNode) -> StatusResponse:
        """
        Receive query as AST (abstract syntax tree) and act upon it somehow.
        Args:
            query (ASTNode): sql query represented as AST. May be any kind
                of query: SELECT, INTSERT, DELETE, etc
        Returns:
            HandlerResponse
        """
        renderer = SqlalchemyRender(DruidDialect)
        query_str = renderer.get_string(query, with_failback=True)
        return self.native_query(query_str)

    def get_tables(self) -> StatusResponse:
        """
        Return list of entities that will be accessible as tables.
        Returns:
            HandlerResponse
        """

        query = """
            SELECT *
            FROM INFORMATION_SCHEMA.TABLES
        """
        result = self.native_query(query)
        df = result.data_frame

        df = df[['TABLE_NAME', 'TABLE_TYPE']]
        result.data_frame = df.rename(columns={'TABLE_NAME': 'table_name', 'TABLE_TYPE': 'table_type'})

        return result

    def get_columns(self, table_name: str) -> StatusResponse:
        """
        Returns a list of entity columns.
        Args:
            table_name (str): name of one of tables returned by self.get_tables()
        Returns:
            HandlerResponse
        """

        query = f"""
            SELECT *
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE "TABLE_SCHEMA" = 'druid' AND "TABLE_NAME" = '{table_name}'
        """
        result = self.native_query(query)
        df = result.data_frame

        df = df[['COLUMN_NAME', 'DATA_TYPE']]
        result.data_frame = df.rename(columns={'COLUMN_NAME': 'column_name', 'DATA_TYPE': 'data_type'})

        return result


connection_args = OrderedDict(
    host={
        'type': ARG_TYPE.STR,
        'description': 'The host name or IP address of Apache Druid.'
    },
    port={
        'type': ARG_TYPE.INT,
        'description': 'The port that Apache Druid is running on.'
    },
    path={
        'type': ARG_TYPE.STR,
        'description': 'The query path.'
    },
    scheme={
        'type': ARG_TYPE.STR,
        'description': 'The URI schema. This parameter is optional and the default will be http.'
    },
    user={
        'type': ARG_TYPE.STR,
        'description': 'The user name used to authenticate with Apache Druid. This parameter is optional.'
    },
    password={
        'type': ARG_TYPE.STR,
        'description': 'The password used to authenticate with Apache Druid. This parameter is optional.'
    }
)

connection_args_example = OrderedDict(
    host='localhost',
    port=8888,
    path='/druid/v2/sql/',
    scheme='http'
)