"""
scanpy QC script RNA
order of QC:
- RNA
- PROT
- Repertoire
- ATAC
"""

import argparse
import logging
import os
import sys
import warnings

import muon as mu
import pandas as pd
import scanpy as sc

from panpipes.funcs.io import write_obs

L = logging.getLogger()
L.setLevel(logging.INFO)
log_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s: %(levelname)s - %(message)s")
log_handler.setFormatter(formatter)
L.addHandler(log_handler)

warnings.simplefilter(action="ignore", category=FutureWarning)

parser = argparse.ArgumentParser()
# required option
parser.add_argument(
    "--sampleprefix", default="", help="prefix to prepend when saving the metadata file"
)
parser.add_argument("--input_anndata", default="adata_unfilt.h5ad", help="")
parser.add_argument("--outfile", default="adata_unfilt.h5ad", help="")
parser.add_argument(
    "--figdir", default="./figures/", help="path to save the figures to"
)
parser.add_argument(
    "--figure_suffix",
    default="_qc-plot.png",
    help="figures filename suffix to be appended to figures/umap",
)
parser.add_argument("--scrubletdir", default=None, help="path to save the figures to")
parser.add_argument(
    "--ccgenes", default=None, help="path to file containing cell cycle genes"
)
parser.add_argument(
    "--customgenesfile",
    default=None,
    help="path to file containing list of genes to quantify",
)
parser.add_argument(
    "--calc_proportions",
    default="mitochondrial,ribosomal",
    help="which list of genes to use to calc proportion of mapped reads over total,per cell?",
)
parser.add_argument(
    "--score_genes",
    default=None,
    help="which list of genes to use to scanpy.tl.score_genes per cell?",
)

args, opt = parser.parse_known_args()
L.info("Running with params: %s", args)

sc.settings.verbosity = 3
figdir = args.figdir

if not os.path.exists(figdir):
    os.mkdir(figdir)

sc.settings.figdir = figdir
sc.set_figure_params(
    scanpy=True, fontsize=14, dpi=300, facecolor="white", figsize=(5, 5)
)


L.info("Reading in MuData from '%s'" % args.input_anndata)
mdata = mu.read(args.input_anndata)
rna = mdata["rna"]


# load the scrublet scores into the anndata (if they have been run)
if args.scrubletdir is not None:
    scrub_dir = args.scrubletdir
    L.info("Merging in the scrublet scores from directory '%s'" % args.scrubletdir)
    sample_ids = rna.obs[["sample_id"]].drop_duplicates()

    # [scrub_dir + "/" + ss + "_scrublet_scores.txt" for ss in sample_ids.sample_id] # ToDo: it was uncommented – why is this here?

    doubletscores = [
        pd.read_csv(scrub_dir + "/" + ss + "_scrublet_scores.txt", sep="\t", header=0)
        for ss in sample_ids.sample_id
    ]

    doubletscores = pd.concat(doubletscores, keys=sample_ids.sample_id).reset_index(
        level="sample_id"
    )
    # rename the barcodes to match up qwith what the rna.obs barcodes are
    if len(sample_ids) > 1:
        doubletscores["barcode"] = (
            doubletscores["barcode"].astype(str)
            + "-"
            + doubletscores["sample_id"].astype(str)
        )
    doubletscores = doubletscores.set_index("barcode").drop("sample_id", axis=1)
    # merge with rna.obs
    rna.obs = rna.obs.merge(
        doubletscores, how="left", left_index=True, right_index=True
    )


# Cell-wise QC based on .var lists of genes

qc_vars = []

if args.customgenesfile is not None:
    if os.path.exists(args.customgenesfile):
        cat_dic = {}
        L.info("Reading in custom genes csv file from '%s'" % args.customgenesfile)
        customgenes = pd.read_csv(args.customgenesfile)
        if not {"group", "feature"}.issubset(customgenes.columns):
            L.error(
                "The custom genes file needs to have both columns, 'group' and 'feature'."
            )
            sys.exit(
                "The custom genes file needs to have both columns, 'group' and 'feature'."
            )
        custom_cat = list(set(customgenes["group"].tolist()))

        for cc in custom_cat:
            cat_dic[cc] = customgenes.loc[
                customgenes["group"] == cc, "feature"
            ].tolist()

        if args.calc_proportions is not None:
            calc_proportions = args.calc_proportions.split(",")
            calc_proportions = [a.strip() for a in calc_proportions]
        else:
            L.warning(
                "No genes passed to `args.calc_proportions` to calculate proportions for"
            )

        if args.score_genes is not None:
            score_genes = args.score_genes.split(",")
            score_genes = [a.strip() for a in score_genes]
        else:
            L.warning("No genes passed to `args.score_genes` to calculate scores for")

    else:
        L.error(
            f"File with custom genes for QC purposes `{args.customgenesfile}` does not exist."
        )
        sys.exit(
            f"File with custom genes for QC purposes `{args.customgenesfile}` does not exist."
        )
else:
    L.error(
        "You have not provided a file with a list of custom genes to use for QC purposes – `args.customgenesfile`."
    )
    sys.exit(
        "You have not provided a file with a list of custom genes to use for QC purposes – `args.customgenesfile`."
    )

for kk in calc_proportions:
    xname = kk
    gene_list = cat_dic[kk]
    rna.var[xname] = [
        x in gene_list for x in rna.var_names
    ]  # annotate the group of hb genes as 'hb'
    qc_vars.append(xname)

qc_info = ""
if qc_vars != []:
    qc_info = " and calculating proportions for '%s'" % qc_vars
L.info("Calculating QC metrics with scanpy.pp.calculate_qc_metrics()" + qc_info)
sc.pp.calculate_qc_metrics(
    rna, qc_vars=qc_vars, percent_top=None, log1p=True, inplace=True
)

if args.score_genes is not None:
    for kk in score_genes:
        L.info("Computing gene scores for '%s'" % kk)
        xname = kk
        gene_list = cat_dic[kk]
        sc.tl.score_genes(
            rna,
            gene_list,
            ctrl_size=min(len(gene_list), 50),
            gene_pool=None,
            n_bins=25,
            score_name=kk + "_score",
            random_state=0,
            copy=False,
            use_raw=None,
        )


if args.ccgenes is not None:
    L.info("Reading in cell cycle genes tsv file from '%s'" % args.ccgenes)
    ccgenes = pd.read_csv(args.ccgenes, sep="\t")
    if not {"cc_phase", "gene_name"}.issubset(ccgenes.columns):
        L.error(
            "The cell cycle genes file needs to have both columns, 'cc_phase' and 'gene_name'."
        )
        sys.exit(
            "The cell cycle genes file needs to have both columns, 'cc_phase' and 'gene_name'."
        )
    sgenes = ccgenes[ccgenes["cc_phase"] == "s"]["gene_name"].tolist()
    g2mgenes = ccgenes[ccgenes["cc_phase"] == "g2m"]["gene_name"].tolist()
    L.info("Calculating cell cycle scores")
    sc.tl.score_genes_cell_cycle(rna, s_genes=sgenes, g2m_genes=g2mgenes)


mdata.update()

L.info(
    "Saving updated obs in a metadata tsv file to ./"
    + args.sampleprefix
    + "_cell_metadata.tsv"
)
write_obs(mdata, output_prefix=args.sampleprefix, output_suffix="_cell_metadata.tsv")
L.info("Saving updated MuData to '%s'" % args.outfile)
mdata.write(args.outfile)

L.info("Done")
