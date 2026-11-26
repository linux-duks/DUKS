import polars as pl

from data_dirs import module_data_file


def load_by_commits(window_date_size=None):
    df = pl.read_parquet(module_data_file("kernel", "by_commit.parquet"))

    return df


# short-hand for appliying the rolling_count
def rolling_count_row_of_lists(
    series: pl.Expr, index_column: str, period: str
) -> pl.Expr:
    """Rolling count of the distinct values in a list column.

    Called from ``with_columns``, so both the argument and the result are
    expressions.
    """
    return (
        series.flatten()
        .drop_nulls()
        .n_unique()
        .rolling(index_column=index_column, period=period)
    )


def load_data(window_date_size="1d"):
    df = pl.read_parquet(module_data_file("kernel", "by_date.parquet")).lazy()

    if window_date_size is None:
        window_date_size = "1d"

    # count number of total contributors over the windw_date_size period
    df = df.with_columns(
        [
            # all_contributors
            rolling_count_row_of_lists(
                pl.col("all_contributors"), "committer_date", window_date_size
            ).alias("rolling_count_contributors"),
            # authors
            rolling_count_row_of_lists(
                pl.col("author"), "committer_date", window_date_size
            ).alias("rolling_count_authors"),
            # committer
            rolling_count_row_of_lists(
                pl.col("committer"), "committer_date", window_date_size
            ).alias("rolling_count_committers"),
            # extra_contributors (not author nor committer)
            rolling_count_row_of_lists(
                pl.col("extra_contributors"), "committer_date", window_date_size
            ).alias("rolling_count_extra_contributors"),
            # emails mentioned as ack
            rolling_count_row_of_lists(
                pl.col("attributions_ack"), "committer_date", window_date_size
            ).alias("attributions_ack"),
            # emails mentioned as reviewers
            rolling_count_row_of_lists(
                pl.col("attributions_reviewed"), "committer_date", window_date_size
            ).alias("attributions_reviewed"),
            # reporters
            rolling_count_row_of_lists(
                pl.col("attributions_reported"), "committer_date", window_date_size
            ).alias("attributions_reported"),
            # suggestions
            rolling_count_row_of_lists(
                pl.col("attributions_suggested"), "committer_date", window_date_size
            ).alias("attributions_suggested"),
            # testers
            rolling_count_row_of_lists(
                pl.col("attributions_tested"), "committer_date", window_date_size
            ).alias("attributions_tested"),
            # author_in_maintainers_file
            rolling_count_row_of_lists(
                pl.col("author_in_maintainers_file"), "committer_date", window_date_size
            ).alias("author_in_maintainers_file"),
            # committer_in_maintainers_file
            rolling_count_row_of_lists(
                pl.col("committer_in_maintainers_file"),
                "committer_date",
                window_date_size,
            ).alias("committer_in_maintainers_file"),
            # extra_attributions_in_maintainers_file
            rolling_count_row_of_lists(
                pl.col("extra_attributions_in_maintainers_file"),
                "committer_date",
                window_date_size,
            ).alias("extra_attributions_in_maintainers_file"),
        ]
    )

    # remove email lists to keep only counts
    df = df.drop(
        "all_contributors",
        "author",
        "attributions",
        "committer",
        "extra_contributors",
    )

    # send date as yyyy-mm-dd
    df = df.with_columns(
        pl.col("committer_date").dt.strftime("%Y-%m-%d").alias("committer_date")
    )

    return df.collect()


# TODO: there are missing tags
def load_tags():
    df = pl.read_csv(
        module_data_file("kernel", "tags.csv"),
        separator="|",
        infer_schema=False,  # try_parse_dates=True
    )

    # TODO: change order ?
    # df = df.sort(
    #     "tag", descending=False, maintain_order=True
    # )
    #

    df = df.with_columns(
        pl.when(pl.col(pl.String).str.len_chars() == 0)
        .then(None)
        .otherwise(pl.col(pl.String))
        .name.keep()
    )

    df = df.group_by(pl.col("tag")).agg(
        pl.col("commit"), pl.col("date").drop_nulls().first()
    )

    # df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    # send date as yyyy-mm-dd
    # df = df.with_columns(pl.col("date").dt.strftime("%Y-%m-%d").alias("date"))

    return df


# main used only to test locally, executing this script directly
if __name__ == "__main__":
    import orjson

    print()
    data = load_tags()
    # data = load_data("14d")
    print(data)
    data.write_ndjson("demo.ndjson")
    print(data.columns)
    print(orjson.dumps(data.tail(10).to_dict(as_series=False)).decode())
