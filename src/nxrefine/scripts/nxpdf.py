import argparse
import os
import subprocess
import sys

import numpy as np
from nexusformat.nexus import *
from nxrefine.nxrefine import NXRefine
from nxrefine.nxreduce import NXMultiReduce, NXReduce


def main():

    parser = argparse.ArgumentParser(description="Calculate PDF transforms")
    parser.add_argument('-d', '--directory', required=True, 
                        help='scan directory')
    parser.add_argument('-o', '--overwrite', action='store_true', 
                        help='overwrite existing transforms')
    parser.add_argument('-q', '--queue', action='store_true',
                        help='add to server task queue')
    
    args = parser.parse_args()
    
    reduce = NXMultiReduce(args.directory, pdf=True, overwrite=args.overwrite)
    if args.queue:
        reduce.queue()
    else:
        reduce.nxpdf()


if __name__=="__main__":
    main()
