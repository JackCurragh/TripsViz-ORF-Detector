"""This script contains functions to transform data frames into different file types"""

import polars as pl
import os

from .findexonscds import getexons_and_cds


def get_bam_tran(bam_df, exon_df):
    """
    Merge BAM and exon DataFrames based on chromosome alignment and calculate transcript coordinates in BAM.

    Parameters:
    - bam_df (DataFrame): DataFrame containing BAM file data with chromosome positions.
    - exon_df (DataFrame): DataFrame containing exon annotations with chromosome positions.

    Returns:
    - dict: A dictionary where keys are column names and values are lists of corresponding values,
            representing transcript coordinates aligned with BAM data.

    This function merges `bam_df` and `exon_df` on the 'chr' column and filters rows where the BAM
    positions fall within exon boundaries (`start_right` to `stop_right`). It then calculates
    transcript coordinates (`tran_start_bam` and `tran_stop_bam`) in the BAM file by adjusting
    coordinates relative to exon boundaries.

    The resulting DataFrame (`df_filtered`) excludes redundant columns (`stop_right`, `start_right`,
    `tran_start`, `tran_stop`) and is converted to a dictionary (`bam_tran_dict`) where each key
    corresponds to a column name and the associated value is a list of values from `df_filtered`.

    Note: This function assumes the use of a library like `pandas` (abbreviated here as `pl`) for
    DataFrame operations.
    """
    df_joined = bam_df.join(exon_df, on="chr")
    df_filtered = df_joined.filter(
        (pl.col("start") >= pl.col("start_right"))
        & (pl.col("stop") <= pl.col("stop_right"))
    )
    df_filtered = df_filtered.with_columns(
        (pl.col("tran_start") + (pl.col("start") - pl.col("start_right"))).alias(
            "tran_start_bam"
        )
    )

    df_filtered = df_filtered.with_columns(
        (pl.col("tran_stop") - (pl.col("stop_right") - pl.col("stop"))).alias(
            "tran_stop_bam"
        )
    ).select(pl.all().exclude("stop_right", "start_right", "tran_start", "tran_stop"))
    bam_tran_dict = df_filtered.to_dict(as_series=False)

    return bam_tran_dict


def bamtranscript(bam_df, exon_df):
    """
    Filter BAM and exon DataFrames based on shared chromosome information and flatten exon annotations.

    Parameters:
    - bam_df (DataFrame): DataFrame containing BAM file data with chromosome positions.
    - exon_df (DataFrame): DataFrame containing exon annotations with chromosome positions.

    Returns:
    - DataFrame: A modified version of `bam_df` and `exon_df` after filtering based on shared
                 chromosome information and exploding exon coordinates.

    This function processes `bam_df` and `exon_df` to filter rows where chromosome information
    is shared between the two datasets. First, it identifies unique chromosomes present in both
    `bam_df` and `exon_df`. Then, it filters `bam_df` to include only rows where the chromosome
    matches those found in `exon_df`, and vice versa for `exon_df`.

    After filtering, `exon_df` is flattened by exploding columns ['start', 'stop', 'tran_start', 'tran_stop']
    to separate comma-separated values into individual rows, facilitating further processing.

    The modified versions of `bam_df` and `exon_df` are returned for subsequent analysis or operations.

    Note: This function assumes the use of a library like `pandas` (abbreviated here as `pl`) for
    DataFrame operations.
    """
    exon_flattened = exon_df.with_columns(pl.col("chr"))

    uniquechr_bam = list(bam_df["chr"].unique())
    uniquechr_exon = list(exon_flattened["chr"].unique())

    bam_df = (
        bam_df.with_columns(shared=pl.col("chr").is_in(uniquechr_exon))
        .filter(pl.col("shared") == True)
        .select(pl.all().exclude("shared"))
    )
    exon_flattened = (
        exon_flattened.with_columns(shared=pl.col("chr").is_in(uniquechr_bam))
        .filter(pl.col("shared") == True)
        .select(pl.all().exclude("shared"))
        .explode(["start", "stop", "tran_start", "tran_stop"])
    )

    results = []
    for chr in bam_df["chr"].unique():
        # Filter exons that overlap with the current bam range
        bam_with_chr = bam_df.filter(pl.col("chr") == chr)
        exon_with_chr = exon_flattened.filter(pl.col("chr") == chr)
        min_val = min(exon_with_chr["start"])
        max_val = max(exon_with_chr["stop"])
        for i in range(min_val, max_val, 225000):
            rng = i + 225000
            exon_chr = exon_with_chr.filter(
                (pl.col("start") >= i) & (pl.col("stop") <= rng)
            )
            bam_chr = bam_with_chr.filter(
                (pl.col("start") >= i) & (pl.col("stop") <= rng)
            )
            if not exon_chr.is_empty() and not bam_chr.is_empty():
                result_dict = get_bam_tran(bam_chr, exon_chr)
                results.append(result_dict)

    bam_df = pl.from_dicts(results)
    bam_df = bam_df.explode(
        [
            "count",
            "chr",
            "start",
            "stop",
            "length",
            "tran_id",
            "tran_start_bam",
            "tran_stop_bam",
        ]
    )
    return bam_df


def asitecalc(df, offsets):
    """
    Calculates A-site positions and aggregates counts based on offset values.

    Parameters:
    - df (DataFrame): Input DataFrame containing 'length' and 'pos' columns for A-site calculation.
    - offsets (dict): Dictionary containing offset values for each 'length' value.

    Returns:
    - df_bed (DataFrame): DataFrame containing aggregated information of A-site positions, their counts, and chromosome information.

    This function calculates the A-site positions based on the provided offsets for different 'length' values.
    It iterates through the input DataFrame 'df' and calculates the A-site positions using the 'pos' column and the corresponding offset value.
    The calculated A-site positions are stored in a new DataFrame 'df_asite' by concatenating the individual A-site DataFrames.

    The function then groups the 'df_asite' DataFrame by chromosome and A-site position, and aggregates the counts of A-site occurrences using the 'agg' function.
    Subsequently, it creates a new DataFrame 'df_tobed' by adding 1 to the A-site position and sorts the DataFrame based on the chromosome and A-site position.
    Finally, the function constructs the 'df_bed' DataFrame by selecting the 'chr', 'A-site', 'end', and 'count' columns, and returns it.

    """
    # GROUP TO CALCULATE A-SITE
    y = []
    for value, data in df.group_by("length"):
        x = (
            df.filter(pl.col("length") == value)
            .with_columns((pl.col("start") + offsets[value]).alias("A-site"))
            .select(
                pl.all().exclude("start", "stop", "length", "tran_id", "bamcds_start")
            )
            .to_dict(as_series=False)
        )
        y.append(x)
    df_asite = pl.from_dicts(y)
    df_asite = df_asite.explode(["chr", "count", "A-site"])
    # GROUP ON A-SITE
    df_asite = df_asite.group_by("chr", "A-site").agg(pl.col("count").sum())
    df_asite = df_asite.with_columns((pl.col("A-site") + 1).alias("stop"))
    df_bed = df_asite.sort(["chr", "A-site"]).select(["chr", "A-site", "stop", "count"])
    return df_bed


def calculate_differences(start, start_dict):
    """
    Calculate the difference between a given start value and each value in a dictionary of start values.

    Parameters:
    - start (int or float): The starting value for which differences are calculated.
    - start_dict (int): A values extracted from a dictionary containing start values (int or float).

    Returns:
    - dict: A dictionary where keys correspond to identifiers from `start_dict` and values represent
            the differences between `start` and each corresponding value in `start_dict`.

    This function computes the difference (`start - start_dict[key]`) for each key-value pair in `start_dict`.
    The result is returned as a dictionary where keys are from `start_dict` and values are the calculated differences.

    Note: This function assumes `start_dict` contains numerical values (integers or floats).
    """
    start_diff = start - start_dict

    return start_diff


def bamrelativetocds(bamdf, cdsdf):
    """
    Filter BAM and CDS DataFrames based on shared transcript IDs and calculate relative start positions.

    Parameters:
    - bamdf (DataFrame): DataFrame containing BAM file data with transcript information.
    - cdsdf (DataFrame): DataFrame containing CDS annotations with transcript information.

    Returns:
    - DataFrame: A modified version of `bamdf` after calculating relative start positions relative to CDS.

    This function processes `bamdf` and `cdsdf` to filter rows where transcript IDs are shared between
    the two datasets. First, it identifies unique transcript IDs present in both `bamdf` and `cdsdf`.
    Then, it filters `bamdf` to include only rows where the transcript ID matches those found in `cdsdf`,
    and vice versa for `cdsdf`.

    Next, it creates a dictionary (`start_dict`) mapping each transcript ID to its corresponding start
    position in `cdsdf`. Using this dictionary, it calculates relative start positions (`bamcds_start`)
    in `bamdf` by subtracting the start position in `cdsdf` from the start position in `bamdf`.

    The modified `bamdf` DataFrame (`bam_df2`) excludes redundant columns (`tran_start_bam`, `tran_stop_bam`)
    and retains only the calculated `bamcds_start` values for each row.

    Note: This function assumes the use of a library like `pandas` (abbreviated here as `pl`) for
    DataFrame operations, and it depends on a helper function `calculate_differences` to perform
    numerical calculations.
    """
    uniquetran_bam = list(bamdf["tran_id"].unique())
    uniquetran_cds = list(cdsdf["tran_id"].unique())

    bam_df = (
        bamdf.with_columns(shared=pl.col("tran_id").is_in(uniquetran_cds))
        .filter(pl.col("shared") == True)
        .select(pl.all().exclude("shared"))
    )
    cds_df = (
        cdsdf.with_columns(shared=pl.col("tran_id").is_in(uniquetran_bam))
        .filter(pl.col("shared") == True)
        .select(pl.all().exclude("shared"))
    )

    tran_dict = cds_df.to_dict(as_series=False)
    start_dict = dict(zip(tran_dict["tran_id"], tran_dict["tran_start"]))

    bam_df2 = bam_df.with_columns(
        [
            pl.struct(["tran_id", "tran_start_bam"])
            .apply(
                lambda x: calculate_differences(
                    x["tran_start_bam"], start_dict[x["tran_id"]]
                )
            )
            .alias("bamcds_start")
        ]
    )

    bam_df2 = bam_df2.select(pl.all().exclude("tran_start_bam", "tran_stop_bam"))
    return bam_df2


def change_point_analysis(offset_df):
    """
    Calculate the change point for the metagene profile
    This should reflect where the cds starts and as a result the
    offset to apply to get a-site

    Inputs:
        read_counts: Dictionary containing the read counts for each position
        surrounding_range: tuple of start and stop for change point analysis

    Outputs:
        max_shift_position: The position of the change point
    """
    max_shift = 0
    max_shift_position = None
    offset_dict = {}
    for length in offset_df["length"].unique():
        offset_df_len = offset_df.filter(pl.col("length") == length).sort(
            "bamcds_start"
        )
        for i in range(-30, 11):
            left = []
            for j in range(i - 3, i + 1):
                left_df = offset_df_len.filter(pl.col("bamcds_start") == j)
                if not left_df.is_empty():
                    left.append(left_df["count"][0])
                else:
                    left.append(0)
            right = []
            for j in range(i + 1, i + 5):
                right_df = offset_df_len.filter(pl.col("bamcds_start") == j)
                if not right_df.is_empty():
                    right.append(right_df["count"][0])
                else:
                    right.append(0)

        mean_left = sum(left) / 4
        mean_right = sum(right) / 4
        shift = abs(mean_right - mean_left)
        if shift > max_shift:
            max_shift = shift
            max_shift_position = i
        if max_shift_position == None:
            offset_dict[length] = 15
        else:
            offset_dict[length] = max_shift_position
    return offset_dict


def dftobed(df, annotation, offsets):
    """
    Converts a DataFrame to BED format with A-site calculation and offset values.

    Parameters:
    - df (DataFrame): Input DataFrame to be converted to BED format.

    Returns:
    - bed (DataFrame): DataFrame representing the BED format data with A-site positions and aggregated counts.

    This function takes an input DataFrame 'df' and performs the following operations:
    1. Creates a new DataFrame 'df_filtered' by calculating the length using the 'end' and 'pos' columns and excluding the 'end' column from the selection.
    2. Splits the 'qname' column values specifically on "_x", applies a split function to extract the integer value, renames the columns to 'count' and 'chr', and stores the results in a new DataFrame 'df_namesplit'.
    3. Obtains the length values from the 'df_namesplit' DataFrame and creates offsets dictionary with a hardcoded offset value of 15 for each length value.
    4. Calls the 'asitecalc' function to calculate A-site positions using the 'df_namesplit' DataFrame and the generated offsets, and stores the resulting BED format data in the 'bed' DataFrame.

    """
    df_filtered = df.with_columns(
        (pl.col("end") - pl.col("pos")).alias("length")
    ).select(
        pl.all().exclude(
            "flag", "qual", "tags", "mapq", "tlen", "seq", "pnext", "rnext", "cigar"
        )
    )

    # split specifically on _x -> implement more!!!
    split_func = lambda s: int(s.split("_x")[1])
    df_namesplit = (
        df_filtered.with_columns(pl.col("qname").apply(split_func))
        .rename({"qname": "count", "rname": "chr", "pos": "start", "end": "stop"})
        .cast({"chr": pl.String})
    )

    cds_df, exon_df = getexons_and_cds(annotation)
    # calculate transcriptomic coordinates
    bam_tran = bamtranscript(df_namesplit, exon_df)
    # Calculate position relative to cds
    bam_to_cds = bamrelativetocds(bam_tran, cds_df)
    if not offsets:
        bam_offsets = bam_to_cds.group_by("bamcds_start", "length").agg(
            pl.col("count").sum()
        )
        # offset dictionary
        offsets = change_point_analysis(bam_offsets)
    # A site calculation
    bed = asitecalc(bam_to_cds, offsets)

    return bed, exon_df, cds_df


def bedtobigwig(bedfile, chromsize, filename):
    """
    Converts a bedGraph file to a bigWig file using the bedGraphToBigWig utility.

    Parameters:
        bedfile (str): The path to the input bedGraph file.
        chromsize (str): The path to the chromosome sizes file.
        filename (str): The name for the generated file.

    Returns:
        None

    Notes:
        - The output bigWig file will be named 'filename.bw' and will be created in the same directory as the input file.
        - Requires the bedGraphToBigWig utility to be installed and accessible in the system path.

    Example:
        bedtobigwig("input.bedGraph", "chromsizes.txt", "filename")
    """
    os.system(f"bedGraphToBigWig {bedfile} {chromsize} {filename}.bw")

    return ""
