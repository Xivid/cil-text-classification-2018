#!/bin/bash
echo "===================CIL Text Classification====================="
echo "Warning: if you have not connected to the ETH VPN, please do so before running this script!"
echo "Warning: please run \"python setup.py install\" in the root directory, or \"pip install gensim\", before running this script!"
echo "===================Downloading dataset========================="

# Move to where this script is located
cd "$(dirname $0)"

echo; echo
echo "Downloading twitter dataset..."
wget -N "http://www.da.inf.ethz.ch/teaching/2018/CIL/material/exercise/twitter-datasets.zip"
unzip -o twitter-datasets.zip

echo; echo
echo "Removing Id column from the test file"
cat twitter-datasets/test_data.txt | cut -d ',' -f 2- > twitter-datasets/test_data_stripped.txt

echo; echo
echo "Downloading Pre-Trained GloVe Word Embeddings for Twitter..."
wget -N http://nlp.stanford.edu/data/glove.twitter.27B.zip
unzip -o glove.twitter.27B.zip -d glove.twitter.27B

echo; echo
echo "Downloading Pre-Trained Word2Vec Embeddings based on Google News.. "
wget -N https://s3.amazonaws.com/dl4j-distribution/GoogleNews-vectors-negative300.bin.gz
gunzip -o GoogleNews-vectors-negative300.bin.gz

echo; echo
echo "Converting GloVe to Word2Vec... (Please ensure you have Python module \"gensim\" installed)"
python3 glove_to_word2vec.py glove.twitter.27B/glove.twitter.27B.50d.txt glove.twitter.27B/glove.twitter.27B.50d.word2vec.txt
python3 glove_to_word2vec.py glove.twitter.27B/glove.twitter.27B.100d.txt glove.twitter.27B/glove.twitter.27B.100d.word2vec.txt
python3 glove_to_word2vec.py glove.twitter.27B/glove.twitter.27B.200d.txt glove.twitter.27B/glove.twitter.27B.200d.word2vec.txt

# Move back
cd -
echo; echo
echo "Done."