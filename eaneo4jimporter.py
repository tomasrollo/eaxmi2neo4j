import io
import os
import sys
from neo4j.v1 import GraphDatabase, basic_auth

DEBUG = True
# DEBUG = False

class EANeo4JImporterException(Exception):
	def __init__(self, value):
		self.value = value
	def __str__(self):
		return repr(self.value)

class EANeo4JImporter(object):

	def __init__(self):
		self.session = None
		self.commitFreq = 1000 # commit DB transaction every 1000 queries
		self.config = {
			'nodes': {
				'parse': self.parseNodes,
				'filename': 'nodes',
				'cypher': 'merge (n {guid: {guid}}) on create set n:%(labels)s, n = {props} on match set n:%(labels)s, n = {props}', # possibly overwrite stubs from other svn branches
			},
			'stubs': {
				'parse': self.parseStubs,
				'filename': 'stubs',
				'cypher': 'merge (n {guid: {guid}}) on create set n:%(labels)s, n = {props} on match set n:%(labels)s',
			},
			'relationships': {
				'parse': self.parsePelationships,
				'filename': 'relationships',
				'cypher': 'match (n:%(prefix)s {guid: {from}}), (m:%(prefix)s {guid: {to}}) merge (n)-[r:%(labels)s {guid: {guid}}]->(m) on create set r = {props}',
			},
			'structureRels': {
				'parse': self.parseStructureRels,
				'filename': 'structureRels',
				'cypher': 'match (n:%(prefix)s {guid: {parent}}), (m:%(prefix)s {guid: {child}}) merge (n)-[r:CONTAINS]->(m) on create set r = {props}',
			},
		}
	
	def parseNodes(self, headers, line):
		chunks = line.split('\t')
		# if len(headers) != len(chunks):
			# raise EANeo4JImporterException('wrong number of chunks on line %d'%(lineNr))
		content = {}
		content['guid'] = chunks.pop(0)
		content['labels'] = self.escapeLabels(chunks.pop(0))
		content['props'] = {}
		content['props']['guid'] = content['guid']
		for p in chunks:
			k,v = p.split('|')
			content['props'][k] = v
		return content
	
	def parseStubs(self, headers, line):
		chunks = line.split('\t')
		content = {}
		content['guid'] = chunks[0]
		content['labels'] = chunks[1]
		content['props'] = {}
		content['props']['guid'] = content['guid']
		content['props']['name'] = chunks[2]
		return content
	
	def parsePelationships(self, headers, line):
		chunks = line.split('\t')
		content = {}
		content['guid'] = chunks.pop(0)
		content['labels'] = self.escapeLabels(chunks.pop(0))
		content['from'] = chunks.pop(0)
		content['to'] = chunks.pop(0)
		content['props'] = {}
		content['props']['guid'] = content['guid']
		for p in chunks:
			k,v = p.split('|')
			content['props'][k] = v
		return content
	
	def parseStructureRels(self, headers, line):
		chunks = line.split('\t')
		content = {}
		content['parent'] = chunks[0]
		content['child'] = chunks[1]
		content['props'] = {}
		return content
	
	def setup(self, host, user, passwd, prefix):
		self.prefix = prefix
		self.driver = GraphDatabase.driver(host, auth=basic_auth(user, passwd))
		print "Successfully connected to %s with user %s and pass *****"%(host, user)
		self.session = self.driver.session()
		if DEBUG: print "Successfully got Neo4J driver session"
	
	def cleanup(self):
		if self.session:
			self.session.close()
	
	def escapeLabels(self, labels): # escapes labels with spaces or colons in them with backticks
		labels = labels.replace('::','||')
		labels = ':'.join([('`%s`'%(l),l)[l.find(' ') == -1] for l in labels.split(':')])
		labels = ':'.join([('`%s`'%(l),l)[l.find('||') == -1] for l in labels.split(':')])
		labels = labels.replace('||','::')
		return labels
	
	def importAll(self, dryrun=False):
		# self.importFile(self.config['nodes'], dryrun)
		# self.importFile(self.config['stubs'], dryrun)
		# self.importFile(self.config['relationships'], dryrun)
		self.importFile(self.config['structureRels'], dryrun)
	
	def importFile(self, config, dryrun=False):
		fname = "%s.%s.csv"%(self.prefix, config['filename'])
		print "Processing file "+fname
		if dryrun:
			print "Running DRY RUN, not writing anything to DB"
		else:
			print "Running for real, writing to DB"
		lineNr = 1
		tx = self.session.begin_transaction()
		headers = []
		
		with io.open(fname,'r',encoding='utf8') as fin:
			if dryrun:
				cypherDump = io.open('cypherDump.%s.tmp'%(fname),'w',encoding='utf8')
			for line in fin:
				if DEBUG: print "Processing file %s lineNr %d"%(fname, lineNr)
				
				line = line.strip('\n').replace('\\','/').replace('"','\\"')
				
				if lineNr == 1: # we expect headers on the first line
					headers = line.split('\t')
					if DEBUG: print "Found headers: %s"%(str(headers))
					lineNr += 1
					continue
				
				# parse the line into content
				if config.get('parse') is not None and callable(config['parse']):
					content = config['parse'](headers, line)
					content['props']['__svn_branch'] = self.prefix
					content['prefix'] = self.prefix
					if config['filename'] in ('nodes','stubs'): # label nodes with svn branch prefix for simpler queries later
						content['labels'] += ':'+self.prefix
					# if config['filename'] == 'stubs': # label stubs with their source
						# del content['props']['__svn_branch']
						# content['props']['__stub_source'] = self.prefix
				else:
					raise EANeo4JImporterException("config['parse'] for %s is not callable"%s(config['filename']))
				
				# prepare the cypher query statement
				cypherQuery = ''
				if not config.get('cypher'):
					raise EANeo4JImporterException("config['cypher'] for %s is missing"%s(config['filename']))
				if content.get('labels'):
					cypherQuery = config['cypher']%({'labels':content['labels'],'prefix':content['prefix']})
				else:
					cypherQuery = config['cypher']%({'prefix':content['prefix']})
				
				# run the query - or not, depending on dry run
				if dryrun:
					cypherDump.write(u'%s, %s\n'%(cypherQuery,content))
				else:
					tx.run(cypherQuery,parameters=content)
				
				# commit after self.commitFreq queries
				if lineNr % self.commitFreq == 0:
					print "Committing transaction to DB"
					tx.success = True
					tx.close()
					tx = self.session.begin_transaction()
				
				lineNr += 1
			if dryrun:
				cypherDump.close()
			fin.close()
		if not tx.closed:
			print "Committing transaction to DB"
			tx.success = True
			tx.close()
		
if __name__ == '__main__':
	
	if len(sys.argv) < 1:
		print "USAGE: python %s prefix [-d]ryrun"%(sys.argv[0])
		sys.exit()
	
	importer = EANeo4JImporter()
	try:
		importer.setup(host='bolt://localhost:7687',user='neo4j',passwd='t$26tFYmRQNjT*J%', prefix=sys.argv[1])
		importer.importAll(dryrun=(len(sys.argv)>2 and sys.argv[2] == '-d'))
	except EANeo4JImporterException as e:
		print 'ERROR: '+str(e)
	finally:
		importer.cleanup()