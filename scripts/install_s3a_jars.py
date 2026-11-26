"""Download the two jars Spark needs to read s3a:// locally (pyspark ships without them).
Versions must match pyspark's bundled Hadoop (3.3.4 for Spark 3.5)."""
import pathlib
import urllib.request

import pyspark

JARS = {
    "hadoop-aws-3.3.4.jar": "https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar",
    "aws-java-sdk-bundle-1.12.262.jar":
        "https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar",
}
target = pathlib.Path(pyspark.__file__).parent / "jars"
for name, url in JARS.items():
    dest = target / name
    if not dest.exists():
        print(f"downloading {name}")
        urllib.request.urlretrieve(url, dest)
print("s3a jars ready in", target)
