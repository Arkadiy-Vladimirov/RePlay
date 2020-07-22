"""
Библиотека рекомендательных систем Лаборатории по искусственному интеллекту.
"""
from typing import Optional

import numpy as np
import pandas as pd
from pyspark.sql import DataFrame
from pyspark.sql import functions as sf
from pyspark.sql import types as st
from scipy.sparse import csc_matrix
from sklearn.linear_model import ElasticNet

from replay.models.base_rec import Recommender
from replay.session_handler import State


class SLIM(Recommender):
    """`SLIM: Sparse Linear Methods for Top-N Recommender Systems
    <http://glaros.dtc.umn.edu/gkhome/fetch/papers/SLIM2011icdm.pdf>`_"""

    similarity: DataFrame
    can_predict_cold_users = True

    def __init__(
        self,
        beta: float = 2.0,
        lambda_: float = 0.5,
        seed: Optional[int] = None,
    ):
        """
        :param beta: параметр l2 регуляризации
        :param lambda_: параметр l1 регуляризации
        :param seed: random seed
        """
        if beta < 0 or lambda_ <= 0:
            raise ValueError("Неверно указаны параметры для регуляризации")
        self.beta = beta
        self.lambda_ = lambda_
        self.seed = seed

    def _fit(
        self,
        log: DataFrame,
        user_features: Optional[DataFrame] = None,
        item_features: Optional[DataFrame] = None,
    ) -> None:
        self.logger.debug("Построение модели SLIM")

        pandas_log = log.select("user_idx", "item_idx", "relevance").toPandas()

        interactions_matrix = csc_matrix(
            (pandas_log.relevance, (pandas_log.user_idx, pandas_log.item_idx)),
            shape=(self.users_count, self.items_count),
        )
        similarity = (
            State()
            .session.createDataFrame(pandas_log.item_idx, st.FloatType())
            .withColumnRenamed("value", "item_id_one")
        )

        alpha = self.beta + self.lambda_
        l1_ratio = self.lambda_ / alpha

        regression = ElasticNet(
            alpha=alpha,
            l1_ratio=l1_ratio,
            fit_intercept=False,
            random_state=self.seed,
            selection="random",
            positive=True,
        )

        @sf.pandas_udf(
            "item_id_one float, item_id_two float, similarity double",
            sf.PandasUDFType.GROUPED_MAP,
        )
        def slim_row(pandas_df):
            """
            Построчное обучение матрицы близости объектов, стохастическим
            градиентным спуском
            :param pandas_df: pd.Dataframe
            :return: pd.Dataframe
            """
            idx = int(pandas_df["item_id_one"][0])
            column = interactions_matrix[:, idx]
            column_arr = column.toarray().ravel()
            interactions_matrix[
                interactions_matrix[:, idx].nonzero()[0], idx
            ] = 0

            regression.fit(interactions_matrix, column_arr)
            interactions_matrix[:, idx] = column
            good_idx = np.argwhere(regression.coef_ > 0).reshape(-1)
            good_values = regression.coef_[good_idx]
            similarity_row = {
                "item_id_one": idx,
                "item_id_two": good_idx,
                "similarity": good_values,
            }
            return pd.DataFrame(data=similarity_row)

        self.similarity = (
            similarity.groupby("item_id_one").apply(slim_row)
        ).cache()

    # pylint: disable=too-many-arguments
    def _predict(
        self,
        log: DataFrame,
        k: int,
        users: DataFrame,
        items: DataFrame,
        user_features: Optional[DataFrame] = None,
        item_features: Optional[DataFrame] = None,
        filter_seen_items: bool = True,
    ) -> DataFrame:
        recs = (
            users.withColumnRenamed("user_idx", "user")
            .join(
                log.withColumnRenamed("item_idx", "item"),
                how="inner",
                on=sf.col("user") == sf.col("user_idx"),
            )
            .join(
                self.similarity,
                how="inner",
                on=sf.col("item") == sf.col("item_id_one"),
            )
            .join(
                items,
                how="inner",
                on=sf.col("item_idx") == sf.col("item_id_two"),
            )
            .groupby("user_idx", "item_idx")
            .agg(sf.sum("similarity").alias("relevance"))
            .select("user_idx", "item_idx", "relevance")
            .cache()
        )

        return recs