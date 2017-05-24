import io
import os
import sys
from neo4j.v1 import GraphDatabase, basic_auth

if __name__ == '__main__':
	driver = GraphDatabase.driver('bolt://localhost:7687', auth=basic_auth('neo4j', 't$26tFYmRQNjT*J%'))
	session = driver.session()
