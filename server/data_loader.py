import polars as pl
import orjson

def load_by_commits(window_date_size=None):
    df = pl.read_parquet("../data/by_commit.parquet")

    return df


# short-hand for appliying the rolling_count
def rolling_count_row_of_lists(
    series: pl.Series, index_column: str, period: str
) -> pl.Series:
    return (
        series.flatten()
        .drop_nulls()
        .n_unique()
        .rolling(index_column=index_column, period=period)
    )


def load_data(window_date_size="1d"):
    if "d" not in window_date_size:
        window_date_size = window_date_size + "d"

    df = pl.read_parquet("../data/by_date.parquet")

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

    return df


# TODO: there are missing tags
def load_tags():
    df = pl.read_csv(
        "../data/tags.csv",
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


def generate_pre_calculated_frames():
    windows = [1, 5, 14, 30, 60, 120, 365]
    for window in windows:
        data = load_data(f"{window}d")
        with open(f"../data/cached_{window}d.json", "wb") as file:
            file.write(orjson.dumps(data.to_dict(as_series=False)))


def load_pre_calculated_frame(window_date_size):
    try:
        with open(f"../data/cached_{window_date_size}d.json", "rb") as f:
            read_bytes = f.read()
            decoded_data = orjson.loads(read_bytes)
            return decoded_data
    except IOError as e:
        print(f"Error reading from file: {e}")
    except orjson.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
    # if loading fails, produce data now
    return load_data(window_date_size=window_date_size).to_dict(as_series=False)


# main used only to test locally, executing this script directly
if __name__ == "__main__":

    generate_pre_calculated_frames()
