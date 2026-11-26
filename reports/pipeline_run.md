# Pipeline run: scale and data quality

* Source rows scanned (all ERC-20 transfers, 2023-07 to 2025-06): **1,013,650,670**
* Stablecoin + oracle rows landed in bronze: **219,373,602**
* Blocks: **5,225,164**
* Bronze ingest time: 72 min on a 4-core machine (local Spark 3.5, reading S3 directly)
* Silver build time: 93 min

## Lake tables
| table                       |      rows |   size_gb |   parquet_files |
|:----------------------------|----------:|----------:|----------------:|
| bronze/stablecoin_transfers |  32578389 |      2.22 |              61 |
| bronze/blocks               |   5225164 |      0.32 |             731 |
| silver/contract_registry    |  78565784 |      2.06 |              16 |
| silver/stablecoin_transfers | 215021088 |     17.88 |             731 |
| gold/daily_kpis             |    106531 |      0    |               4 |
| gold/hourly_activity        |    410270 |      0.01 |               4 |
| gold/wallet_daily           |  85591294 |      4.04 |              96 |
| gold/wallet_monthly         |  42388103 |      1.8  |               8 |
| gold/wallet_profile         |  23850148 |      1.12 |               8 |

Bronze transfer partitions older than the last two months were deleted after silver was built, because the
local machine has a small disk allowance. In AWS the same rule is an S3 lifecycle policy (bronze is
replayable from the public source). Full bronze row counts are in the batch table below.

## Data quality checks (all runs)
| dataset                     |   checks |   passed |   failed_error |   warned |
|:----------------------------|---------:|---------:|---------------:|---------:|
| bronze_blocks               |      150 |      150 |              0 |        0 |
| bronze_stablecoin_transfers |      275 |      275 |              0 |        0 |
| gold                        |        4 |        4 |              0 |        0 |
| silver_contract_registry    |        2 |        2 |              0 |        0 |
| silver_stablecoin_transfers |      286 |      286 |              0 |        0 |

## Bronze batches
| batch   |   days |   all_token_transfers_scanned |   bronze_rows |   blocks |   seconds |
|:--------|-------:|------------------------------:|--------------:|---------:|----------:|
| 2023-07 |     31 |                      35745165 |       5385256 |   220924 |     156.2 |
| 2023-08 |     31 |                      36869732 |       5430846 |   221554 |     143.3 |
| 2023-09 |     30 |                      33083574 |       5158530 |   213977 |     151   |
| 2023-10 |     31 |                      35608942 |       6372575 |   221578 |     149.3 |
| 2023-11 |     30 |                      34979342 |       6532778 |   214308 |     151.4 |
| 2023-12 |     31 |                      35073230 |       7149724 |   221044 |     136   |
| 2024-01 |     31 |                      35712123 |       7426747 |   220994 |     151.2 |
| 2024-02 |     29 |                      35139527 |       6326862 |   206718 |     149.6 |
| 2024-03 |     31 |                      40409171 |       7706039 |   220682 |     191.6 |
| 2024-04 |     30 |                      41190675 |       7713604 |   214271 |     154   |
| 2024-05 |     31 |                      39780964 |       7848013 |   221690 |     164.6 |
| 2024-06 |     30 |                      41536748 |       7244362 |   214699 |     152.8 |
| 2024-07 |     31 |                      43768417 |       7751164 |   222024 |     156.1 |
| 2024-08 |     31 |                      44165331 |       9097864 |   222021 |     187.8 |
| 2024-09 |     30 |                      42522378 |       8494298 |   214925 |     158.3 |
| 2024-10 |     31 |                      44265675 |       7741579 |   222150 |     192   |
| 2024-11 |     30 |                      42428383 |       9146812 |   214865 |     198.5 |
| 2024-12 |     31 |                      43372202 |       9893732 |   221957 |     180.4 |
| 2025-01 |     31 |                      46106191 |      10317386 |   222059 |     188.6 |
| 2025-02 |     28 |                      44424987 |      12408826 |   200342 |     193.7 |
| 2025-03 |     31 |                      66984312 |      14602295 |   222043 |     273.8 |
| 2025-04 |     30 |                      49115839 |      17045921 |   214959 |     219.1 |
| 2025-05 |     31 |                      49986473 |      16120454 |   220849 |     261.8 |
| 2025-06 |     30 |                      51381289 |      16457935 |   214531 |     262   |
