F6.7 high-flow leave-one-flood-out test, LSTM + GR4J (plan/06-forecast.md), built by
.github/workflows/highflow-lstm.yml run 45106299004
(https://github.com/maggioniduffy/clima-ideas/actions/runs/45106299004) at commit eda079d576c13350928a26742d510df9abc22017.
Not code; can be deleted after use.
Files: report/F6.7.md and F6.7.json (the report); work/pretrain (CAMELS-CL pretraining: norm.json,
pretrain.json, model_seed*.pt, history); work/fold-YYYY (per fold: fold.json, sims.parquet,
inputs.parquet, lstm_seed*.pt weights, lstm_history_seed*.json, lstm_config.json).
Config: the defaults of `clima-nqn flow highflow` (5 seeds, 10 pretraining + up to 30 fine-tuning
epochs, 20000 windows per epoch), one job per (fold, seed); no scoring in the training jobs.
Sources: daily flow and ERA5 forcing from branches data/f25-flow and data/f25-forcing
(SNIH flow; Copernicus ERA5, licence-to-use with attribution); GEFSv12 reforecast from
data/f53-alldays (NOAA NODD: open, attribution requested, no NOAA endorsement implied) and the
operational GEFS 0.25 deg windows of the 2020-2025 floods (NOAA NODD, same terms);
pretraining on CAMELS-CL: Alvarez-Garreton et al. (2018), HESS 22, 5817-5846, PANGAEA
DOI 10.1594/PANGAEA.894885, CC-BY-4.0 (CR2MET forcing, not ERA5).
Not an official alert system: retrospective test for technical users.
