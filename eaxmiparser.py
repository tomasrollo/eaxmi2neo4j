import io
import os
import sys
import re
import csv
from bs4 import BeautifulSoup as bs

# blacklist for xml attributes that we don't want to parse out of the XMI
attributeBlacklist = (
'visibility',
'isLeaf',
'isAbstract',
'isOrdered',
'targetScope',
'changeable',
'isNavigable',
'isActive',
'isRoot',
)
# blacklist for tagged values that we don't want to parse out of the XMI
taggedValueBlacklist = (
'$ea_xref_property',
'actorkind',
'atomic',
'batchload',
'batchsave',
'complexity',
'conditional',
'containment',
'created',
'deststyle',
'date_created',
'date_modified',
'difficulty',
'dst_aggregation',
'dst_containment',
'dst_changeable',
'dst_isNavigable',
'dst_isOrdered',
'dst_style',
'dst_targetScope',
'dst_visibility',
'ea_localid',
'ea_sourceID',
'ea_sourceName',
'ea_sourceType',
'ea_stype',
'ea_targetID',
'ea_targetName',
'ea_targetType',
'functiontype',
'gentype',
'headStyle',
'iconstyle',
'isAbstract',
'isActive',
'isprotected',
'isSpecification',
'keywords',
'lastloaddate',
'lastsavedate',
'lastupdate',
'lb',
'linecolor',
'linemode',
'lineStyle',
'linewidth',
'logxml',
'lt',
'mb',
'mt',
'object_style',
'packageFlags',
'phase',
'prerequisite',
'priority',
'privatedata5',
'product_name',
'rb',
'reqtype',
'rotation',
'seqno',
'showdecoration',
'sourcestyle',
'src_aggregation',
'src_containment',
'src_changeable',
'src_isNavigable',
'src_isOrdered',
'src_style',
'src_targetScope',
'src_visibility',
'stability',
'style',
'styleex',
'tagged',
'tpos',
'usedtd',
'version',
'virtualInheritance',
'xmiver',
'modified',
)

DEBUG = True
# DEBUG = False

# base exception class for reporting errors during parsing, just an empty exception
class EAParserException(Exception):
	def __init__(self, value):
		self.value = value
	def __str__(self):
		return repr(self.value)

class EANoGUIDException(EAParserException):
	pass

# Basic abstract class, handles parsing out of most generic properties common for both nodes and relationships
# Inherited by more specific classes further down
class EANode(object):
	UMLtype = 'EANode'
	def __init__(self):
		self.rawguid = ''
		self.guid = ''
		self.props = {}
		self.stereotypes = []
		self.taggedValues = {}
		self.name = ''
		self.isStub = False
	def populate(self,bselem,parser):
		if DEBUG: print "EANode.populate START"
		
		# parse out very basic properties - guid and name
		self.rawguid = bselem.get('xmi.id','')
		if self.rawguid == '':
			# print "%s without GUID, skipping"%(self.UMLtype)
			raise EANoGUIDException("%s without GUID, skipping"%(self.UMLtype))
		self.guid = EAXMIUtils.cleanGUID(self.rawguid)
		print "Processing "+self.rawguid
		self.name = bselem.get('name','').replace("\n","<br>")
		
		# parse out properties
		for (k,v) in bselem.attrs.items():
			if k not in attributeBlacklist and k not in ('xmi.id','name'): # filter out unwanted attributes
				if k in ('parent','namespace','package'): self.props[k] = EAXMIUtils.cleanGUID(v)
				else: self.props[k] = v
		
		# parse out tagged values
		taggedValuesTag = bselem.find('ModelElement.taggedValue',recursive=False)
		if taggedValuesTag is not None:
			for tv in taggedValuesTag.find_all('TaggedValue',recursive=False):
				if tv.get('value') is None: # skip tagged values without a value (e.g. embedded documents)
					continue
				if tv['tag'] not in taggedValueBlacklist:
					if tv['tag'] in ('parent','namespace','package','package2','owner'): self.taggedValues[tv['tag']] = EAXMIUtils.cleanGUID(tv['value']) # clean guids for certain tagged values
					else: self.taggedValues[tv['tag']] = tv['value'].strip().replace("\n","<br>").replace("\t","    ").replace("|"," ")
		# if self.taggedValues.get('documentation') is not None: self.taggedValues['documentation'] = self.taggedValues['documentation']
		
		# parse out stereotype(s)
		stereotypes = set()
		stereotypesTag = bselem.find('ModelElement.stereotype',recursive=False)
		if stereotypesTag is not None:
			for st in stereotypesTag.find_all('Stereotype',recursive=False):
				if st.get('name') is not None:
					stereotypes.add(st['name'])
		if self.taggedValues.get('stereotype') is not None:
			stereotypes.add(self.taggedValues['stereotype'])
			del self.taggedValues['stereotype']
		self.stereotypes = [s for s in list(stereotypes) if s.count(' ') < 2] # filter out stereotypes containing spaces
		
		if self.taggedValues.get('savedasstub','') == 'true':
			self.isStub = True
		if DEBUG: print "EANode.populate END"
	def __str__(self):
		return "%s(%s) %s %s {%s}"%(self.UMLtype, ";".join(self.stereotypes), self.name, self.guid, "; ".join(["%s=%s"%(k,v) for (k,v) in self.taggedValues.items()]))
	def __repr__(self):
		return "<%s '%s'>"%(self.UMLtype, self.name)
	# formats a CSV header string for outputting into CSV file
	@staticmethod
	def getCSVHeader():
		return u'\t'.join(['guid', 'labels', 'props'])
	# formats the node into CSV record
	def getCSV(self):
		return u'\t'.join([self.guid, ":".join(self.stereotypes+[self.UMLtype]), u'name|'+self.name])
	# formats the node properties into CSV record
	def getProps(self):
		props = {'UMLType':self.UMLtype}
		if len(self.stereotypes) > 0:
			props['stereotype'] = self.stereotypes[0]
		if len(self.stereotypes) > 1:
			props['stereotypes'] = ','.join(self.stereotypes)
		for k,v in self.props.items():
			props[k] = v
		for k,v in self.taggedValues.items():
			props[k] = v
		return u'\t'.join([u'%s|%s'%(k,props[k]) for k in sorted(props.keys())])

# specific class for parsing out package elements from the XMI file
class UMLPackage(EANode):
	UMLtype = 'Package'
	def populate(self,bselem,parser):
		if DEBUG: print "UMLPackage.populate START"
		super(UMLPackage,self).populate(bselem,parser)
		if DEBUG: print 'Processing children'
		
		# empty packages can be saved as stubs and in such case need to be loaded from some other XMI file
		if self.isStub:
			if self.taggedValues.get('xmlpath') is None:
				raise EAParserException('Missing xmlpath taggedValue property for package GUID=%s saved as stub in file %s'%(self.guid, parser.fname))
			# include the XMI file where the package of the stub is actually stored in the list of files to be processed further
			fileToAdd = self.taggedValues['xmlpath']
			if fileToAdd not in parser.filesToProcess: # add each file only once
				if DEBUG: print 'Adding file %s to parser.filesToProcess'%(fileToAdd)
				parser.filesToProcess.append(fileToAdd)
		
		# TODO: add deriving of structural relationships using the owner, package and package2 properties
		
		# process ownedElement part of package xmi
		owElement = bselem.find('Namespace.ownedElement')
		if owElement is not None: # packages might be empty
			for child in owElement.children:
				if DEBUG: print "Processing child %s of type %s"%(child.name, type(child))
				if child.name in EAXMIParser.elementNames: # only process known and parseable elements
					if DEBUG: print "Found known type of child, going to process now"
					parser.processElement(child.name, child)
				elif child.name == 'ActivityModel': # search for ActionStates (business functions)
					actionStates = child.find_all('ActionState')
					if DEBUG: print "Found %d ActionState elements"%len(actionStates)
					for ac in actionStates:
						parser.processElement(ac.name, ac)
				else: # note elements that we skip
					if child.name not in parser.skippedElementTypes: parser.skippedElementTypes.append(child.name)
		
		if DEBUG: print 'Finished processing children'
		if DEBUG: print "UMLPackage.populate END"
		return self.isStub

# specific classes for various types of UML elements in the XMI file
class UMLComponent(EANode):
	UMLtype = 'Component'

class UMLClass(EANode):
	UMLtype = 'Class'

class UMLActor(EANode):
	UMLtype = 'Actor'

class UMLEvent(EANode):
	UMLtype = 'Event'

class UMLInterface(EANode):
	UMLtype = 'Interface'

class UMLNode(EANode):
	UMLtype = 'Node'

class UMLPseudoState(EANode):
	UMLtype = 'PseudoState'

class UMLTransition(EANode):
	UMLtype = 'Transition'

class UMLUseCase(EANode):
	UMLtype = 'UseCase'

class UMLActionState(EANode):
	UMLtype = 'ActionState'
	# def __init__(self):
		# super(UMLActionState,self).__init__()
	# def populate(self,bselem,parser):
		# super(UMLActionState,self).populate(bselem,parser)

# Abstract class for relationships, defines mandatory from and to properties
class EARelationShip(EANode):
	UMLtype = 'EARelationShip'
	# each relationship must have a from and to property
	def __init__(self):
		super(EARelationShip,self).__init__()
		self.from_ = ''
		self.to = ''
	def populate(self,bselem,parser):
		if DEBUG: print "EARelationShip.populate START"
		super(EARelationShip,self).populate(bselem,parser)
		if DEBUG: print "EARelationShip.populate END"
	def setFrom(self,from_):
		self.from_ = EAXMIUtils.cleanGUID(from_)
	def setTo(self,to):
		self.to = EAXMIUtils.cleanGUID(to)
	@staticmethod
	def getCSVHeader(node=False):
		return u'\t'.join(['guid', 'labels', 'from', 'to', 'props'])
	def getCSV(self, node=False):
		tp = self.UMLtype
		if len(self.stereotypes) > 0:
			tp = self.stereotypes[0]
		return u'\t'.join([self.guid, tp, self.from_, self.to, u'name|'+self.name])
	
class UMLGeneralization(EARelationShip):
	UMLtype = 'Generalization'
	def __init__(self):
		super(UMLGeneralization,self).__init__()
	def populate(self,bselem,parser):
		if DEBUG: print "UMLGeneralization.populate START"
		super(UMLGeneralization,self).populate(bselem,parser)
		self.setFrom(self.props['subtype'])
		self.setTo(self.props['supertype'])
		if DEBUG: print "UMLGeneralization.populate START"

class UMLDependency(EARelationShip):
	UMLtype = 'Dependency'
	def __init__(self):
		super(UMLDependency,self).__init__()
	def populate(self,bselem,parser):
		if DEBUG: print "UMLDependency.populate START"
		super(UMLDependency,self).populate(bselem,parser)
		self.setTo(self.props['supplier'])
		self.setFrom(self.props['client'])
		if DEBUG: print "UMLDependency.populate END"

class UMLAssociation(EARelationShip):
	UMLtype = 'Association'
	def __init__(self):
		super(UMLAssociation,self).__init__()
	def populate(self,bselem,parser):
		if DEBUG: print "UMLAssociation.populate START"
		super(UMLAssociation,self).populate(bselem,parser)
		ends = bselem.find('Association.connection',recursive=False).find_all('AssociationEnd',recursive=False)
		self.props['end1_aggregation'] = ends[0].get('aggregation','')
		self.props['end1_multiplicity'] = ends[0].get('multiplicity','')
		self.props['end1_name'] = ends[0].get('name','')
		self.setFrom(ends[0].get('type',''))
		self.props['end2_aggregation'] = ends[1].get('aggregation','')
		self.props['end2_multiplicity'] = ends[1].get('multiplicity','')
		self.props['end2_name'] = ends[1].get('name','')
		self.setTo(ends[1].get('type',''))
		if DEBUG: print "UMLAssociation.populate END"

class UMLAssociationRole(EARelationShip):
	UMLtype = 'AssociationRole'
	def __init__(self):
		super(UMLAssociationRole,self).__init__()
	def populate(self,bselem,parser):
		if DEBUG: print "UMLAssociationRole.populate START"
		super(UMLAssociationRole,self).populate(bselem,parser)
		ends = bselem.find('Association.connection',recursive=False).find_all('AssociationEndRole',recursive=False)
		self.props['end1_aggregation'] = ends[0].get('aggregation','')
		self.props['end1_multiplicity'] = ends[0].get('multiplicity','')
		self.props['end1_name'] = ends[0].get('name','')
		self.setFrom(ends[0].get('type',''))
		self.props['end2_aggregation'] = ends[1].get('aggregation','')
		self.props['end2_multiplicity'] = ends[1].get('multiplicity','')
		self.props['end2_name'] = ends[1].get('name','')
		self.setTo(ends[1].get('type',''))
		if DEBUG: print "UMLAssociationRole.populate END"

class StructuralRelationship(object):
	UMLtype = 'StructuralRelationship'
	def __init__(self, parent, child):
		self.from_ = parent # from
		self.to = child # to
	@staticmethod
	def getCSVHeader():
		return "\t".join(['parent', 'child'])
	def getCSV(self):
		return "\t".join([self.from_, self.to])
	def getProps(self):
		return u''
	def __repr__(self):
		return "<%s '%s'->'%s'>"%(self.UMLtype,EAXMIUtils.shortenGUID(self.from_), EAXMIUtils.shortenGUID(self.to))

class EAStub(object):
	UMLtype = 'EAStub'
	def __init__(self, guid):
		self.guid = guid
		self.name = 'Unknown external reference'
	@staticmethod
	def getCSVHeader():
		return "\t".join(['guid','labels','name'])
	def getCSV(self):
		return "\t".join([self.guid,self.UMLtype,self.name])
	def __repr__(self):
		return "<%s '%s'>"%(self.UMLtype,self.name)

# helper class with useful functions
class EAXMIUtils(object):
	# derives relative path for XMI file from it's directory and filename
	@staticmethod
	def getRelPath(dirname, filename):
		return dirname+os.path.sep+'..'+os.path.sep+filename

	# converts GUID from XMI format (with underscores and prefix) to EA format (with dashes)
	guidRegex = re.compile(r"([0-9a-f]{8})_([0-9a-f]{4})_([0-9a-f]{4})_([0-9a-f]{4})_([0-9a-f]{12})", re.IGNORECASE)
	@staticmethod
	def cleanGUID(line):
		line = line.replace('EAID_','').replace('EAPK_','')
		return EAXMIUtils.guidRegex.sub("{\g<1>-\g<2>-\g<3>-\g<4>-\g<5>}", line)

	# shortens GUID for pretty-printing in text outputs, e.g. logs
	@staticmethod
	def shortenGUID(guid):
		return guid[0:4]+'...'+guid[-6:]
	
# main parser class
class EAXMIParser(object):
	
	def __init__(self):
		if DEBUG: print 'creating new EAXMIParser instance'
		self.cleanup()
		if DEBUG: print 'EAXMIParser instantiated'
	
	# cleanup of internal structures (useful between repeated parser runs)
	def cleanup(self):
		if DEBUG: print 'Doing cleanup'
		self.entities = {
			'nodes': [],
			'relationships': [],
			'structureRels': [],
			'stubs': [],
		}
		self.filesToProcess = [] # queue of files to be processed, starts with the file given on command line and continuing with files identified during parsing out packages
		self.s = None
		self.guids = [] # list of all processed GUIDs
		self.rawguids = [] # list of all processed GUIDs in raw form
		self.duplicateGuids = [] # list of all found duplicate GUIDs, mostly for reporting
		self.skippedElementTypes = [] # list of all elements skipped during parsing, mostly for reporting

	# elements that are supposed to be parsed out of the XMI
	elements = {
		'Component': {'class_': UMLComponent, 'type_': 'node'},
		'Package': {'class_': UMLPackage, 'type_': 'node'},
		'Class': {'class_': UMLClass, 'type_': 'node'},
		'ActionState': {'class_': UMLActionState, 'type_': 'node'},
		'Generalization': {'class_': UMLGeneralization, 'type_': 'rel'},
		'Dependency': {'class_': UMLDependency, 'type_': 'rel'},
		'Association': {'class_': UMLAssociation, 'type_': 'rel'},
		'AssociationRole': {'class_': UMLAssociationRole, 'type_': 'rel'},
		'Actor': {'class_': UMLActor, 'type_': 'node'},
		'Event': {'class_': UMLEvent, 'type_': 'node'},
		'Interface': {'class_': UMLInterface, 'type_': 'node'},
		'Node': {'class_': UMLNode, 'type_': 'node'},
		'PseudoState': {'class_': UMLPseudoState, 'type_': 'node'},
		'Transition': {'class_': UMLTransition, 'type_': 'node'},
		'UseCase': {'class_': UMLUseCase, 'type_': 'node'},
	}
	elementNames = elements.keys()
	
	# generic method to process any parseable XMI element
	def processElement(self, tagName, node):
		r = self.elements[tagName]['class_']() # instantiate the right UML* class
		try:
			r.populate(node,self)
			r.props['__load_file'] = self.fname
			r.props['__load_hashindex'] = self.fname+':'+r.rawguid
			# add the previously parsed out tagged values
			tvs = self.taggedValues.get(r.rawguid)
			if tvs is not None:
				for (tag,value) in tvs:
					r.taggedValues[tag] = value
		except EANoGUIDException as e: # element without GUID
			print "ERROR: "+str(e)
		
		if r.name == 'EARootClass': # skip the EARootClass element since it's in every xml file and is useless
			if DEBUG: print "Skipping EARootClass"
			return
		if r.isStub: # skip stubs
			print "Found package savedasstub, not storing, skipping"
			return
		if r.rawguid in self.rawguids: # skip entitites with duplicate GUIDs (sometimes elements in XMI files have duplicite GUIDs)... 
			print "WARNING: %s with duplicite GUID %s"%(r.UMLtype, r.rawguid)
			self.duplicateGuids.append(r.rawguid) # ...but note them for reporting
			return
		
		# store all important information, like GUIDs, rawGUIDs and the resulting entity objects as well
		self.rawguids.append(r.rawguid)
		self.guids.append(r.guid)
		if self.elements[tagName]['type_'] == 'node':
			self.entities['nodes'].append(r)
		elif self.elements[tagName]['type_'] == 'rel':
			self.entities['relationships'].append(r)
		else:
			raise EAParserException('Unknown element type '+self.elements[tagName]['type_'])
	
	# method for parsing a single XMI file
	# not to be used directly, use parseXMIFile(self, <filename>, followLinks=False) to parse a single file
	def parseSingleXMIFile(self, filename):
		print 'Parsing file '+filename
		if not os.path.isfile(filename):
			raise EAParserException('%s is not a file'%filename)
		if filename[-4:] != '.xml':
			raise EAParserException('%s needs to have .xml extension'%filename)
		self.fname = os.path.basename(filename)
		self.s = bs(open(filename),'xml')
		
		# parse out added Tagged Values stored at the end of the XML file first so we can later enrich the elements when parsing them
		XMIcontentElement = self.s.find('XMI.content')
		if XMIcontentElement is None:
			raise EAParserException('Couldn\'t find XMI.Content element in xml file '+filename)
		self.taggedValues = {}
		for tv in XMIcontentElement.find_all('TaggedValue',recursive=False):
			if tv.get('value') is None: # skip tagged values without a value (e.g. embedded documents)
				continue
			if tv['tag'] not in taggedValueBlacklist:
				if tv['modelElement'] not in self.taggedValues.keys():
					self.taggedValues[tv['modelElement']] = []
				if DEBUG: print "adding tagged value %s to element %s"%(tv['tag'],tv['modelElement'])
				self.taggedValues[tv['modelElement']].append((tv['tag'],tv['value'].strip().replace("\n","<br>")))
		
		# now parse out all the elements recursively, starting with a topmost package in the file
		modelElement = self.s.find('Model')
		if modelElement is None:
			raise EAParserException('Couldn\'t find UML:Model element in xml file '+filename)
		owElement = modelElement.find('Namespace.ownedElement')
		if owElement is None:
			raise EAParserException('Couldn\'t find Namespace.ownedElement element under UML:Model in xml file '+filename)
		packageElement = owElement.find('Package')
		if packageElement is None:
			raise EAParserException('Couldn\'t find UML:Package element under Namespace.ownedElement in xml file '+filename)
		self.processElement(packageElement.name, packageElement)
		
		# cleanup a little bit
		self.fname = ''
		self.s = None
		print 'Finished parsing file '+filename
		
	# method for recursively parsing out the whole XMI file tree, starting with a specified file and continuing with other files found during parsing of packages
	def parseXMIFile(self, filename, followLinks=True):
		self.cleanup()
		if not followLinks:
			if DEBUG: print "NOT following links"
			self.parseSingleXMIFile(filename)
		else:
			if DEBUG: print 'Following links'
			dirname = os.path.dirname(filename)
			if dirname == '': # in case we're directly in the directory of the first file
				dirname == '.'
			print "Operating directory with files is "+dirname
			self.filesToProcess.append('ea'+os.path.basename(filename)[0]+os.path.sep+os.path.basename(filename))
			while len(self.filesToProcess) > 0:
				if DEBUG: print '%d files waiting to be processed'%(len(self.filesToProcess))
				self.parseSingleXMIFile(EAXMIUtils.getRelPath(dirname, self.filesToProcess.pop(0)))
		# self.markDupliciteGUIDs()
		self.generateStructureRels()
		self.generateStubs()
		return self.entities
	
	# find and mark entities with duplicite guids (not used anymore)
	def markDupliciteGUIDs(self):
		if DEBUG: print "Mark duplicite GUIDs START"
		for entity in self.entities['nodes']:
			if entity.rawguid in self.duplicateGuids:
				entity.props['load_duplicate'] = 'yes'
		for entity in self.entities['relationships']:
			if entity.rawguid in self.duplicateGuids:
				entity.props['load_duplicate'] = 'yes'
		if DEBUG: print "Mark duplicite GUIDs END"

	# generates structure relationships
	def generateStructureRels(self):
		if DEBUG: print "Generate structural relationships START"
		top = True
		for e in self.entities['nodes']:
			if top:
				top = False
				continue # skip the first package - the top of the tree, its parent is not present
			if e.UMLtype == 'Package' and e.taggedValues.get('parent') is not None:
				self.entities['structureRels'].append(StructuralRelationship(e.taggedValues.get('parent'),e.guid))
			elif e.taggedValues.get('package') is not None:
				self.entities['structureRels'].append(StructuralRelationship(e.taggedValues.get('package'),e.guid))
		if DEBUG: print "Generate structural relationships END"

	# generates stubs for all unresolved external references
	def generateStubs(self):
		if DEBUG: print "Generate stubs START"
		for r in self.entities['relationships']:
			if r.from_ not in self.guids and r.from_ not in self.entities['stubs']:
				self.entities['stubs'].append(r.from_)
			if r.to not in self.guids and r.to not in self.entities['stubs']:
				self.entities['stubs'].append(r.to)
		if DEBUG: print "Generate stubs END"
	
	# generate CSV files with all the parsed-out entities
	def writeEntities(self, prefix):
		print "Writing results to files with prefix: "+prefix

		print "Writing %d nodes"%(len(self.entities['nodes']))
		with io.open(prefix+".nodes.csv",'w',encoding='utf8') as fout:
			fout.write(u''+EANode.getCSVHeader()+"\n")
			for e in self.entities['nodes']:
				fout.write(u''+e.getCSV()+'\t'+e.getProps()+'\n')
			fout.close()

		print "Writing %d relationships"%(len(self.entities['relationships']))
		with io.open(prefix+".relationships.csv",'w',encoding='utf8') as fout:
			fout.write(u''+EARelationShip.getCSVHeader()+"\n")
			for e in self.entities['relationships']:
				fout.write(u''+e.getCSV()+'\t'+e.getProps()+'\n')
			fout.close()

		print "Writing %d structure relationships"%(len(self.entities['structureRels']))
		with io.open(prefix+".structureRels.csv",'w',encoding='utf8') as fout:
			fout.write(u''+StructuralRelationship.getCSVHeader()+"\n")
			for e in self.entities['structureRels']:
				fout.write(u''+e.getCSV()+"\n")
			fout.close()

		# print "Writing properties for %d entities"%(len(self.entities['nodes'])+len(self.entities['relationships']))
		# with io.open(prefix+".properties.csv",'w',encoding='utf8') as fout:
			# fout.write(u'type\tguid\tname\tvalue\n')
			# for e in self.entities['nodes']:
				# fout.write(u'n\t'+e.getProps())
			# for e in self.entities['relationships']:
				# fout.write(u'r\t'+e.getProps())
			# fout.close()

		print "Writing %d stubs"%len(self.entities['stubs'])
		with io.open(prefix+".stubs.csv",'w',encoding='utf8') as fout:
			fout.write(u''+EAStub.getCSVHeader()+"\n")
			for e in self.entities['stubs']:
				stub = EAStub(e)
				fout.write(u''+stub.getCSV()+"\n")
			fout.close()

		print "Writing GUIDs (%d GUIDs)"%len(self.rawguids)
		with io.open(prefix+".GUIDs.csv",'w',encoding='utf8') as fout:
			for rawguid in self.rawguids:
				fout.write(u''+rawguid+'\n')
			fout.close()

		print "Finished writing results"

	def writeEntitiesCSV(self, prefix):
		print "Writing results to files with prefix: "+prefix

		print "Writing %d nodes"%(len(self.entities['nodes']))
		with io.open(prefix+".nodes.csv",'w',encoding='utf8') as fout:
			fout.write(u''+EANode.getCSVHeader()+"\n")
			for e in self.entities['nodes']:
				fout.write(u''+e.getCSV()+"\n")
			fout.close()

		print "Writing %d relationships"%(len(self.entities['relationships']))
		# with io.open(prefix+".relationshipNodes.csv",'w',encoding='utf8') as fout:
			# fout.write(u''+EARelationShip.getCSVHeader(node=True)+"\n")
			# for e in self.entities['relationships']:
				# fout.write(u''+e.getCSV(node=True)+"\n")
			# fout.close()
		with io.open(prefix+".relationships.csv",'w',encoding='utf8') as fout:
			fout.write(u''+EARelationShip.getCSVHeader()+"\n")
			for e in self.entities['relationships']:
				fout.write(u''+e.getCSV()+"\n")
			fout.close()

		print "Writing %d structure relationships"%(len(self.entities['structureRels']))
		with io.open(prefix+".structureRels.csv",'w',encoding='utf8') as fout:
			fout.write(u''+StructuralRelationship.getCSVHeader()+"\n")
			for e in self.entities['structureRels']:
				fout.write(u''+e.getCSV()+"\n")
			fout.close()

		print "Writing properties for %d entities"%(len(self.entities['nodes'])+len(self.entities['relationships']))
		with io.open(prefix+".properties.csv",'w',encoding='utf8') as fout:
			fout.write(u'guid\tname\tvalue\n')
			for e in self.entities['nodes']:
				fout.writelines(e.getProps())
			for e in self.entities['relationships']:
				fout.writelines(e.getProps())
			fout.close()

		print "Writing %d stubs"%len(self.entities['stubs'])
		with io.open(prefix+".stubs.csv",'w',encoding='utf8') as fout:
			fout.write(u''+EAStub.getCSVHeader()+"\n")
			for e in self.entities['stubs']:
				stub = EAStub(e)
				fout.write(u''+stub.getCSV()+"\n")
			fout.close()

		print "Writing GUIDs (%d GUIDs)"%len(self.rawguids)
		with io.open(prefix+".GUIDs.csv",'w',encoding='utf8') as fout:
			for rawguid in self.rawguids:
				fout.write(u''+rawguid+'\n')
			fout.close()

		print "Finished writing results"

if __name__ == '__main__':
	parser = EAXMIParser()
	parser.parseXMIFile(sys.argv[1])
	parser.writeEntities(sys.argv[2])
	print "Following elements were not parsed:"
	print "\n".join(['- '+str(el) for el in parser.skippedElementTypes])