"""
Библиотека рекомендательных систем Лаборатории по искусственному интеллекту.
"""
import logging
import multiprocessing
import os
import unittest
import warnings
from typing import Dict, List, Optional

import pandas as pd
from pyspark.ml.linalg import DenseVector
from pyspark.sql import DataFrame, SparkSession

from sponge_bob_magic.session_handler import State


class PySparkTest(unittest.TestCase):
    def assertSparkDataFrameEqual(
            self,
            df1: DataFrame,
            df2: DataFrame,
            msg: Optional[str] = None
    ) -> None:
        def _unify_dataframe(df: DataFrame):
            pandas_df = df.toPandas()
            columns_to_sort_by: List[str] = []

            if len(pandas_df) == 0:
                columns_to_sort_by = pandas_df.columns
            else:
                for column in pandas_df.columns:
                    if not type(pandas_df[column][0]) in {DenseVector, list}:
                        columns_to_sort_by.append(column)

            return (pandas_df
                    [sorted(df.columns)]
                    .sort_values(by=sorted(columns_to_sort_by))
                    .reset_index(drop=True))

        try:
            pd.testing.assert_frame_equal(_unify_dataframe(df1),
                                          _unify_dataframe(df2),
                                          check_like=True)
        except AssertionError as e:
            raise self.failureException(msg) from e

    def assertDictAlmostEqual(
            self,
            d1: Dict,
            d2: Dict,
            msg: Optional[str] = None) -> None:
        try:
            self.assertSetEqual(set(d1.keys()), set(d2.keys()))
            for key in d1:
                self.assertAlmostEqual(d1[key], d2[key])
        except AssertionError as e:
            raise self.failureException(msg) from e

    @classmethod
    def create_testing_pyspark_session(cls):
        return (SparkSession
                .builder
                .master("local[1]")
                .config("spark.driver.memory", "512m")
                .config("spark.sql.shuffle.partitions", "1")
                .config("spark.local.dir",
                        os.path.join(os.environ["HOME"], "tmp"))
                .appName("testing-pyspark")
                .enableHiveSupport()
                .getOrCreate())

    @classmethod
    def setUpClass(cls):
        multiprocessing.set_start_method("spawn", force=True)
        logger = logging.getLogger()
        logger.setLevel("WARN")
        warnings.filterwarnings(action="ignore", category=ResourceWarning)
        cls.spark = State(cls.create_testing_pyspark_session()).session
        cls.spark.sparkContext.setLogLevel("ERROR")
