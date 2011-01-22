#!/usr/bin/python

import os
import os.path as path
import sys
import optparse
import shutil
import re
import time
import fcntl, fcntl, select
import popen2
from tempfile import NamedTemporaryFile
import commands
import urllib
from xdg.Mime import get_type as mime_type


VERSION="1.6"
FIELDS = {	"1.0" : ["hash","filename","filesize","backupset","stored_to_external","media_title"],
				"1.1" : ["hash","filename","filesize","backupset","stored_to_external","media_title"],
				"1.2" : ["hash","filename","filesize","backupset","stored_to_external","media_title"],
				"1.3" : ["hash","filename","filesize","backupset","stored_to_external","media_title"],
				"1.4" : ["hash","filename","filesize","backupset","stored_to_external","media_title"],
				"1.5" : ["hash","filename","filesize","backupset","stored_to_external","media_title"],
				"1.6" : ["hash","filename","filesize","backupset","stored_to_external","media_title"]}
IMAGES = re.compile(r"\.jpg$|\.cr2$|\.jpeg$|\.tiff$|\.tif$|\.avi$|\.mov",re.IGNORECASE)
#UPDATE_URL = "http://langdal.dk/backupdates"
UPDATE_URL = "http://langdal.dyndns.org:81/backupdates/backupdates"
PROGRESS_PATTERN=re.compile(r"(\d+\.\d{2})%")
RANGE_FILENAME = re.compile(r"(\d{4})(\d{2})(\d{2})(-|_(\d{2})(\d{2})((\d{2}))?)?")
RANGE_FILENAME_GROUPS = {	"year"	: 0,
									"month"  : 1,
									"day" 	: 2,
									"hour" 	: 4,
									"minute" : 5,
									"second" : 7
								}
								
RANGE = re.compile(r"((\d{4})(:(\d{2})(:(\d{2})(:(\d{2})(:(\d{2}))?)?)?)?)-((\d{4})(:(\d{2})(:(\d{2})(:(\d{2})(:(\d{2}))?)?)?)?)")
RANGE_GROUPS={	"from_year" 	: 1,
					"from_month"	: 3,
					"from_day"		: 5,
					"from_hour"		: 7,
					"from_minute"	: 9,
					"to_year"		: 11,
					"to_month"		: 13,
					"to_day"			: 15,
					"to_hour"		: 17,
					"to_minute"		: 19					
					}

class Backup:
	def __init__(self,options):
		self.options = options
		self.options.source = path.abspath(self.options.source)
		self.options.destination = path.abspath(self.options.destination)
		self.tmpBackupInfoFile = None
		self.thumbnailCommand = "exiv2"
		self.o = OutputText()
		try:
			if self.options.undo:
				self.prelaunchCheckDestination()
				self.undo()
				self.abort(0)
			if self.options.create_thumbnails:
				self.prelaunchCheckDestination()
				self.prelaunchCheckThumbnails()
				self.createThumbnails()
				self.abort(0)
			if self.options.statistics:
				self.prelaunchCheckDestination()
				self.printStatistics()
				self.abort(0)
			if self.options.burn:
				self.startBurn()
				self.abort(0)
			if self.options.clean:
				self.clean()
				self.abort(0)
			self.prelaunchCheck()
			self.createNewBackupSet()
			self.startBackup()
		except KeyboardInterrupt:
			self.abort(1)
		
	def prelaunchCheck(self):
		self.prelaunchCheckSource()
		self.prelaunchCheckDestination()
		self.prelaunchCheckThumbnails()		

	def prelaunchCheckSource(self):
		if not path.isdir(self.options.source):
			print red("The specified source directory does not exist")
			self.abort(1)
		
	def prelaunchCheckDestination(self):
		if self.options.clean_destination:
			answer = raw_input(bold("About to completely remove %s. Do you really want to continue? [y/N] " % self.options.destination))
			if answer not in ("Y","y"):
				self.abort(0) 
			else:
				print red(bold("Removing %s" % (self.options.destination)))
				shutil.rmtree(self.options.destination,True,None)

		if not path.exists(self.options.destination):
			if not self.options.clean_destination:
				answer = raw_input(bold("The destination directory does not exist, should it be created? [Y/n] "))
				if (answer not in ("Y","y","")):
					self.abort(0)
			print "Creating directory %s" % self.options.destination
			os.makedirs(self.options.destination)
			if not path.exists(self.options.destination):
				print >> sys.stderr, red(bold("Could not create directory: %s" % self.options.destination))
				print >> sys.stderr, red(bold("Please check permissions"))
		elif not path.isdir(self.options.destination):
			print >> sys.stderr, red(bold("Destination exists, but it is a file. Please remove the file or supply another directory as destination"))
			self.abort(1)

	def prelaunchCheckThumbnails(self):
		if self.options.thumbnails:
			cmd = commands.getoutput("which %s" % self.thumbnailCommand)
			if cmd == "": self.options.thumbnails = False
			else: 
				self.thumbnailCommand = cmd
				if not self.options.thumbnail_directory.startswith("/"):
					self.options.thumbnail_directory = path.join(self.options.destination,self.options.thumbnail_directory)
				else:
					self.options.thumbnail_directory = path.abspath(self.options.thumbnail_directory)
				if not path.isdir(self.options.thumbnail_directory):
					if self.options.verbose: print blue("Creating thumbnail directory %s" % self.option.thumbnail_directory)
					os.makedirs(self.options.thumbnail_directory)
					if not path.isdir(self.options.thumbnail_directory):
						print >> sys.stderr, bad("Could not create thumbnail directory %s" % self.options.thumbnail_directory)
						self.abort(1)
			
	def createNewBackupSet(self):
		self.backupSetName = time.strftime("%Y%m%d-%H%M",time.localtime())
		
	def abort(self,exitCode):
		if self.tmpBackupInfoFile != None:
			self.tmpBackupInfoFile.close()
		if exitCode != 0: print bad("\nAborting")
		sys.exit(exitCode)
		
	def startBackup(self):
		if self.options.verbose: print blue("Starting backup process")
		self.previousBackupSet = self.getPreviousBackupSet()
		self.currentBackupSet = self.getCurrentBackupSet()
		self.filesToBackup = self.getFilesToBackup()
		if len(self.filesToBackup) != 0:
			self.backupFiles()
		else:
			print "Nothing to backup"
		
	def getPreviousBackupSet(self):
		filename = path.join(self.options.destination,self.options.backup_info_file)
		if path.exists(filename):
			if not path.isfile(filename):
				print >> sys.stderr, red(bold("%s is not a valid file"))
				self.abort(1)
			return self.readBackupInfoFile(filename)
		else:
			if self.options.verbose: print blue("No previous backup info file found, creating new")
			self.createNewBackupInfoFile(filename)
			return self.readBackupInfoFile(filename)

	def createNewBackupInfoFile(self,filename):
		"""Creates a new backup info file"""
		if self.options.verbose: print blue("Creating new backup info file %s" % filename)
		backupInfoFile = open(filename,"w")
		print >> backupInfoFile, "%%version=%s" % (VERSION)
		backupInfoFile.close()
			
	def readBackupInfoFile(self,filename):
		"""Reads the existing backup info file"""
		self.backupSetSize = 0
		if self.options.verbose: print blue("Reading existing backup info file %s" % filename)
		backupSet = {}
		backupInfoFile = open(filename,"r")
		while True:
			line = backupInfoFile.readline()
			if line == "": break
			if line.strip() == "":
				continue
			if line.startswith("%"):
				self.handleMetaData(line[1:].strip())
				continue
			hash,value = self.parseLine(line)
			if not backupSet.has_key(hash):
				backupSet[hash] = []
			backupSet[hash].append(value)
			self.backupSetSize += 1
		return backupSet
					

	def handleMetaData(self,metadata):
		"""Handles a line of meta data from backup info file"""
		if self.options.verbose: print "Handling %s" % (metadata)
		key,data = metadata.split("=")
		if key == "version": self.backupInfoFields = FIELDS[data]

	def getCurrentBackupSet(self):
		"""Scans source directory and generates a backup set"""
		print "Scanning source directory..."
		backupSet = {}
		self.collected = []
		self.collecting = True
		path.walk(self.options.source,self._sourceScanner,backupSet)
		self.collecting = False
		self.scanCount = 0
		self.o.setMax(len(self.collected))
		self.o.begin("Scanning %d source files..." % len(self.collected))
		path.walk(self.options.source,self._sourceScanner,backupSet)
		self.o.end()
		return backupSet
		
	def _sourceScanner(self,backupSet,dirname,names):
		#if self.options.verbose: print "\tScanning %s" % dirname
		#if not self.collecting:
		#	self.o.title = "Scanning %s" % dirname
		for name in names:
			filename = path.join(dirname,name)
			if path.isdir(filename) and path.islink(filename) and self.options.follow_symlinks: path.walk(dirname,self._sourceScanner,backupSet)
			if path.isfile(filename):
				if self.options.images:
					t = mime_type(filename)
					if not (t.media == "image" or t.media == "video"):
						continue
					#if not IMAGES.search(filename):
					#	continue
				if self.collecting:
					self.collected.append(filename)
				else:
					self.scanCount += 1
					self.o.setProgress(self.scanCount)
					self.o.update()
					hash = self.getHash(filename)
					if not backupSet.has_key(hash):
						backupSet[hash] = []
					backupSet[hash].append([filename])
				
				
	def getHash(self,filename):
		cmd = "md5sum '%s'" % (filename)
		child = os.popen(cmd)
		hash = child.read()
		return hash.split()[0]
		
	def getFilesToBackup(self):
		filesToBackup = []
		for hash,files in self.currentBackupSet.items():
			if not self.previousBackupSet.has_key(hash):
				filesToBackup.append((hash,files))
			else:
				previousFiles = self.previousBackupSet[hash]
				found = False
				equals = []
				for previousEntry in previousFiles:
					for file in files:
						base = file[0][len(path.commonprefix([file[0],self.options.source])):].lstrip("/")
						if base in previousEntry[0]:
							found = True
						else:
							equals.append(previousEntry[0])
				if not found:
					if self.options.verbose:
						pass
					newFiles = []
					for f in files:
						newFiles.append(f[0][len(path.commonprefix([f[0],self.options.source])):].lstrip("/"))
					print warn("Duplicate:"), "image already backed up under different name: %s == %s" % (newFiles,equals)
					if not self.options.only_hash: filesToBackup.append((hash,[[file[0]]]))
		return filesToBackup
	
	def backupFiles(self):
		backupDir = path.join(self.options.destination,self.backupSetName)
		thumbDir = self.options.thumbnail_directory
		if path.exists(backupDir):
			answer =  raw_input(bold("There seems to be a backupset from within the last minute, should I proceed? [y/N] "))
			if not answer in ("y", "Y"):
				self.abort(0)
		else:
			if not self.options.dry_run: os.makedirs(backupDir)
		progress = 0
		self.o.setMax(len(self.filesToBackup))
		if not self.options.verbose: self.o.begin("Copying %d files..." % (len(self.filesToBackup)))
		backupInfoFile = open(path.join(self.options.destination,self.options.backup_info_file),"a+")
		for hash,files in self.filesToBackup:
			progress += 1
			if not self.options.verbose: 
				self.o.setProgress(progress)
				self.o.update()
			for file in files:
				s = path.commonprefix([self.options.source,file[0]])
				filename = file[0][len(s):].lstrip("/")
				target = path.join(backupDir,filename)
				if self.options.verbose: print blue("\tCopy: %s -> %s" % (file[0],target))
				if not path.isdir(path.dirname(target)):
					if not self.options.dry_run: os.makedirs(path.dirname(target))
				if not self.options.dry_run:
					if path.isfile(target):
						print >> sys.stderr, bad("File exists whith same name but files differ: %s" % (target))
						self.abort(1)
					shutil.copyfile(file[0],target)
					if self.options.thumbnails:
						thumbFile = path.join(thumbDir,filename)
						if not path.isdir(path.dirname(thumbFile)): os.makedirs(path.dirname(thumbFile))
						cmd = '%s -l "%s" -et "%s"' % (self.thumbnailCommand,path.dirname(thumbFile),target)
						o = commands.getoutput(cmd)
					if self.options.verify:
						pass
					if path.isfile(target):
						print >> backupInfoFile, self.createLine(hash,target)
					else:
						print >> sys.stderr, bad("File could not be copied: %s" % target)
		backupInfoFile.close()
		if not self.options.verbose: self.o.end()
		
	def parseLine(self,line):
		s = line.strip().split(",")
		if len(s) != len(self.backupInfoFields):
			print >> sys.stderr, red(bold("Syntax error in backup info file: %s" % line))
			self.abort(1)
		hash = s[0]
		filename = s[1]
		size = s[2]
		backupSetName = s[3]
		storedExternally = s[4]
		mediaTitle = s[5]
		return s[0],[filename,size,backupSetName,storedExternally,mediaTitle]
		
	def createLine(self,hash,target):
		stat = os.stat(target)
		s = path.commonprefix([target,path.join(self.options.destination,self.backupSetName)])
		filename = target[len(s):].lstrip("/")
		line = "%s,%s,%s,%s,%s,%s" % (hash,filename,stat.st_size,self.backupSetName,False,"Unknown")
		return line
		
	def startBurn(self):
		print "Starting burn process"
		if not path.isdir(self.options.destination):
			print >> sys.stderr, red(bold("Directory not found %s" % self.options.destination))
			self.abort(1)
		else:
			if not path.isfile(path.join(self.options.destination,self.options.backup_info_file)):
				print >> sys.stderr, red(bold("No previous backup found in %s" % self.options.destination))
				self.abort(1)
		previousBackupSet = self.getPreviousBackupSet()
		fileCount = 0
		totalSize = 0
		filesToBeStored = {}
		for hash,entries in previousBackupSet.items():
			if not filesToBeStored.has_key(hash):
				filesToBeStored[hash] = []
			unique = {}
			for entry in entries:
				unique[entry[0]] = entry
			for entry in unique.values():
				if self.includeFile(entry): 
					fileCount += 1
					totalSize += int(entry[self.backupInfoFields.index("filesize")-1])
					filesToBeStored[hash].append(entry)
		if fileCount == 0:
			print "No files needs to be backed up"
			self.abort(0)
		else:
			print blue("%d files found, total size %d mb" % (fileCount,(totalSize/1024/1024)))
		default = "%s" % (time.asctime(time.localtime()))
		if self.options.range != "all":
			### TODO format default name using regexp
			##default = self.options.range
			default = "%s-%s" % (self._range_min,self._range_max)
			
		answer = raw_input(bold("What should the media label be? default [%s] " % default))
		if answer == "":
			self.mediaTitle = default
		else:
			self.mediaTitle = answer
		if self.storeFiles(filesToBeStored,previousBackupSet):
			self.storeBackupInfo(previousBackupSet,path.join(self.options.destination,self.options.backup_info_file),backup=True)
		else:
			print >> sys.stderr, red(bold("Unknown error during burn"))
			self.abort(1)
		
	def storeFiles(self,fileList,backupSet):
		files = []
		for hash,entries in fileList.items():
			es = backupSet[hash]
			for entry in entries:
				if not entry in es:
					print >> sys.stderr, red(bold("Error during backup"))
					self.abort(1)
				else:
					bs = entry[self.backupInfoFields.index("backupset")-1]
					name = entry[self.backupInfoFields.index("filename")-1]
					target = name
					files.append((path.join(bs,name),target))
					es[es.index(entry)][self.backupInfoFields.index("stored_to_external")-1] = True
					es[es.index(entry)][self.backupInfoFields.index("media_title")-1] = self.mediaTitle
		return self.doStore(files,backupSet)

	def doStore(self,files,backupSet):
		if not self.options.dry_run:
			self.tmpBackupInfoFile = NamedTemporaryFile(mode='w', bufsize=-1, suffix='', prefix='tmp', dir=None)
			self.storeBackupInfo(backupSet,self.tmpBackupInfoFile.name,close=False)
			files.append((self.tmpBackupInfoFile.name,self.options.backup_info_file))
		if self.options.iso:
			if self.options.target != None:
				target = self.options.target
			else:
				target = "./"
			isoFileName = path.abspath(path.join(target,self.mediaTitle) + ".iso")
			self.o.begin("Creating ISO file %s" % isoFileName)
			self.o.setMax(100)
			#print "Creating ISO file %s" % (isoFileName)
			mkisofsCmd = 'mkisofs -gui -graft-points -R -J -o "%s"' % isoFileName
			pathSpecs = ""
			for source,target in files:
				s = path.join(self.options.destination,source)
				pathSpecs += ' "%s"="%s"' % (target,s)
			pathSpecs += ' "%s"="%s"' % (path.basename(sys.argv[0]),path.abspath(sys.argv[0]))
			#print mkisofsCmd+pathSpecs
			#system.command(mkisofsCmd+pathSpecs)
			runCmd(mkisofsCmd+pathSpecs,self.showProgress)
			self.o.setProgress(100)
			self.o.end()
			if not self.options.dry_run: self.tmpBackupInfoFile.close()
			return True
		elif self.options.target != None:
			if not path.isdir(self.options.target):
				print "Creating target directory: %s" % self.options.target
				if not self.options.dry_run: 
					os.makedirs(self.options.target)
					if not path.isdir(self.options.target):
						print >> sys.stderr, red(bold("Error creating directory %s" % self.options.target))
						self.abort(1)
			progress = 0
			self.o.setMax(len(files))
			if not self.options.verbose: self.o.begin("Copying %d files..." % len(files))
			for source,target in files:
				if not self.options.verbose:
					progress += 1
					self.o.setProgress(progress)
					self.o.update()
				s = path.join(self.options.destination,source)
				t = path.join(self.options.target,target)
				if not path.isdir(path.dirname(t)) and not self.options.dry_run:
					os.makedirs(path.dirname(t))
				if self.options.verbose: print blue("Copy %s -> %s" % (s,t))
				if self.options.dry_run: continue
				shutil.copyfile(s,t)
				if not path.isfile(t):
					if self.options.verbose: print >> sys.stderr, red(bold("Error creating file %s" % t))
					if not self.options.verbose: self.o.end(errmsg="Error creating file %s" % t)
					return False
			if not self.options.verbose: self.o.end()
			if not self.options.dry_run:
				self.tmpBackupInfoFile.close()
				shutil.copyfile(path.abspath(sys.argv[0]),path.join(self.options.target,path.basename(sys.argv[0])))
			return True
		else:
			return False
			
	def showProgress(self,line):
		m = PROGRESS_PATTERN.search(line)
		if m:
			self.progressShower(float(m.groups()[0]))
		
	def storeBackupInfo(self,backupSet,file,close=True,backup=False):
		"""Stores backupSet in backup info file"""
		if self.options.dry_run: return
		header = self.createHeader()
		lines = []
		for hash,entries in backupSet.items():
			for entry in entries:
				s = hash
				for e in entry:
					s += ","+e.__str__()
				s += "\n"
				lines.append(s)

		##f = open("temp","w")
		if not self.options.dry_run:
			if backup:
				shutil.copyfile(file,file+"~")
			f = open(file,"w")
			f.write(header)
			f.writelines(lines)
			if close: f.close()

	def createHeader(self):
		s = ""
		s += "%%version=%s\n" % VERSION
		return s		
		
	def includeFile(self,entry):
		include = True
		if entry[self.backupInfoFields.index("stored_to_external")-1] == "True":
			include = False
		if include and self.options.range != "all":
			if not self.__dict__.has_key("_range_groups"):
				self._range_groups = RANGE.match(self.options.range).groups()
				self._range_from_str	= ""
				self._range_from_str	+= fixNumber(self._range_groups[RANGE_GROUPS["from_year"]])
				self._range_from_str	+= fixNumber(self._range_groups[RANGE_GROUPS["from_month"]])
				self._range_from_str += fixNumber(self._range_groups[RANGE_GROUPS["from_day"]])
				self._range_from_str	+= fixNumber(self._range_groups[RANGE_GROUPS["from_hour"]])
				self._range_from_str	+= fixNumber(self._range_groups[RANGE_GROUPS["from_minute"]])
				self._range_from = int(self._range_from_str)

				self._range_to_str	= ""
				self._range_to_str	+= fixNumber(self._range_groups[RANGE_GROUPS["to_year"]])
				self._range_to_str	+= fixNumber(self._range_groups[RANGE_GROUPS["to_month"]])
				self._range_to_str += fixNumber(self._range_groups[RANGE_GROUPS["to_day"]])
				self._range_to_str	+= fixNumber(self._range_groups[RANGE_GROUPS["to_hour"]])
				self._range_to_str	+= fixNumber(self._range_groups[RANGE_GROUPS["to_minute"]])
				self._range_to = int(self._range_to_str)
				
				self._range_min = self._range_to
				self._range_max = self._range_from
				
			filename = path.basename(entry[self.backupInfoFields.index("filename")-1])
			m = RANGE_FILENAME.search(filename)
			if m:
				g = m.groups()
				fileInfos = ""
				fileInfos += fixNumber(g[RANGE_FILENAME_GROUPS["year"]])
				fileInfos += fixNumber(g[RANGE_FILENAME_GROUPS["month"]])
				fileInfos += fixNumber(g[RANGE_FILENAME_GROUPS["day"]])
				fileInfos += fixNumber(g[RANGE_FILENAME_GROUPS["hour"]])
				fileInfos += fixNumber(g[RANGE_FILENAME_GROUPS["minute"]])
				filedate = int(fileInfos)
				if filedate < self._range_from or filedate > self._range_to: 
					include = False
				else:
					self._range_min = min(filedate,self._range_min)
					self._range_max = max(filedate,self._range_max)
			else:
				include = False
				#a,b = self.options.range.split(":")
				#if filename < a or filename > b: include = False
		return include
	
	def progressShower(self,progress):
		self.o.setProgress(int(progress))
		self.o.update()
		
	def createThumbnails(self):
		backupSet = self.getPreviousBackupSet()
		progress = 0
		self.o.setMax(self.backupSetSize)
		self.o.begin("Creating thumbnails")
		for hash,entries in backupSet.items():
			for entry in entries:
				progress += 1
				self.o.setProgress(progress)
				self.o.update()
				filename = entry[self.backupInfoFields.index("filename")-1]
				backupSetName = entry[self.backupInfoFields.index("backupset")-1]
				source = path.join(path.join(self.options.destination,backupSetName),filename)
				target = path.join(self.options.thumbnail_directory,filename)
				if not path.isfile(source): continue
				if not path.isdir(path.dirname(target)): os.makedirs(path.dirname(target))
				cmd = '%s -f -l "%s" -et "%s"' % (self.thumbnailCommand,path.dirname(target),source)
				commands.getoutput(cmd)
		self.o.end()
		
	def printStatistics(self):
		statistics = self.getStatistics()
		if statistics.has_key("Unknown"):
			totalCount,storedCount,totalSize,storedSize = statistics["Unknown"]
			print "%d (%d mb) files are not stored externally" % (totalCount,(totalSize/1024/1024))
		else:
			print "All files are stored externally"
		for key,value in statistics.items():
			totalCount,storedCount,totalSize,storedSize = value
			if key != "Unknown":
				if storedCount == 0: 
					print """Backup set "%s" contains %d (%d mb) files""" % (key,totalCount,(totalSize/1024/1024))
				else:
					print """Backup set "%s" contains %d (%d mb) files locally and %d (%d mb) files externally""" % (key,totalCount,(totalSize/1024/1024),storedCount,(storedSize/1024/1024))
		
	def getStatistics(self):
		backupSet = self.getPreviousBackupSet()
		statistics = {}
		for hash,entries in backupSet.items():
			for entry in entries:
				filename = entry[self.backupInfoFields.index("filename")-1]
				backupSet = entry[self.backupInfoFields.index("backupset")-1]
				mediaTitle = entry[self.backupInfoFields.index("media_title")-1]
				stored = entry[self.backupInfoFields.index("stored_to_external")-1]
				filesize = int(entry[self.backupInfoFields.index("filesize")-1])
				target = path.join(self.options.destination,path.join(backupSet,filename))
				if not statistics.has_key(mediaTitle):
					statistics[mediaTitle] = (0,0,0,0)
				totalCount,storedCount,totalSize,storedSize = statistics[mediaTitle]
				if path.isfile(target):
					totalCount = totalCount+1
					totalSize = totalSize+filesize
				if stored: 
					storedCount += 1
					storedSize += filesize				
				
				statistics[mediaTitle] = (totalCount,storedCount,totalSize,storedSize)
		return statistics
	
	def clean(self):
		backupSet = self.getPreviousBackupSet()
		filesToDelete = {}
		for hash,entries in backupSet.items():
			for entry in entries:
				filename = entry[self.backupInfoFields.index("filename")-1]
				backupSet = entry[self.backupInfoFields.index("backupset")-1]
				mediaTitle = entry[self.backupInfoFields.index("media_title")-1]
				stored = entry[self.backupInfoFields.index("stored_to_external")-1]
				target = path.join(self.options.destination,path.join(backupSet,filename))
				if stored == "True" and path.isfile(target):
					if not filesToDelete.has_key(mediaTitle):
						filesToDelete[mediaTitle] = []
					filesToDelete[mediaTitle].append(target)
		always = False
		if len(filesToDelete) == 0:
			print "Found no files to be deleted"
		else:
			print "Removig files already stored externally..."
		for mediaTitle,files in filesToDelete.items():
			if not always: 
				answer = raw_input(red("About to remove %d files from backup set %s. Do you want to continue? [a/y/N] " % (len(files),mediaTitle)))
				if not answer in ("y","Y","a","A"):
					continue
				if answer in ("a","A"): always = True
			print "Deleting %s" % mediaTitle
			for f in files:
				if not path.isfile(f):
					print >> sys.stderr, bad("Could not find file %s" % f)
					self.abort(1)
				if not self.options.dry_run:
					os.remove(f)
					
	def undo(self):
		t = path.join(self.options.destination,self.options.backup_info_file)
		s = t+"~"
		answer = raw_input(red("Do you really want to undo? [y/N] "))
		if answer in ("y","Y"):
			if path.isfile(t):
				shutil.copyfile(s,t)
			else:
				print bad("No undo information available!")
				self.abort(1)
				
def runCmd(cmd,callback):
	child = popen2.Popen3(cmd, True)
	#print 'Running: [%d] %s' % (child.pid,cmd)
	#args['pids-to-kill'].append((child.pid,cmd))
	child.tochild.close()
	lines = []
	errors = []
	outfile = child.fromchild
	outfd = outfile.fileno()
	errfile = child.childerr
	errfd = errfile.fileno()
	makeNonBlocking(outfd)
	makeNonBlocking(errfd)
	outeof = erreof = False
	while child.poll() == -1:
		try:
			l = outfile.readline()
			lines.append(l)
			callback(l)
		except: pass
		try:
			e = errfile.readline()
			callback(e)
			#if e:
			#	errors.append(e.strip())
			#	logging.debug(e.strip())
		except: pass
	err = child.wait()
	return lines,errors
	#print errors
	#print lines

def makeNonBlocking(fd):
	fl = fcntl.fcntl(fd, fcntl.F_GETFL)
	try:
		fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NDELAY)
	except AttributeError:
		fcntl.fcntl(fd, fcntl.F_SETFL, fl | fcntl.FNDELAY)

				
def fixNumber(number):
	if number == None: return "00"
	else: return number

def update(opt, value, parser, *args, **kwargs):
	print "Checking %s for updates..." % UPDATE_URL
	res = urllib.urlopen(UPDATE_URL)
	lines = res.readlines()
	data = {}
	for line in lines:
		if line.startswith("%"):
			splitLine = line[1:].strip().split("=")
			data[splitLine[0]] = splitLine[1]
	if not data.has_key("version"):
		print >> sys.stderr, bad("Could not load update information")
		sys.exit(1)
	if data["version"] > VERSION:
		answer = raw_input(red("New version available %s, do you want to update? [Y/n] " % data["version"]))
		if not answer in ("n","N"):
			url = data["url"]
			filename,headers = urllib.urlretrieve(url)
			md5 = commands.getoutput("md5sum %s" % filename).split()[0]
			currentmd5 = commands.getoutput("md5sum %s" % sys.argv[0]).split()[0]
			if not data.has_key(currentmd5):
				print >> sys.stderr, bad("The current script is not updatable, sorry!")
				sys.exit(1)
			elif data[currentmd5] != VERSION:
				print >> sys.stderr, bad("The current script is not updatable, sorry!")
				sys.exit(1)
			if md5 != data["md5"]:
				print >> sys.stderr, bad("Error in update, hash mismatch!")
				sys.exit(1)
			shutil.copyfile(sys.argv[0],sys.argv[0]+"-"+VERSION)
			shutil.copyfile(filename,sys.argv[0])
			print good("Update complete!")
			sys.exit(0)
	print "No valid updataes available"

	sys.exit(0)


"""Adds color to your life"""
colors = {}
colors["reset"]="\x1b[0m"
colors["bold"]="\x1b[01m"

colors["teal"]="\x1b[36;06m"
colors["turquoise"]="\x1b[36;01m"

colors["fuscia"]="\x1b[35;01m"
colors["purple"]="\x1b[35;06m"

colors["blue"]="\x1b[34;01m"
colors["darkblue"]="\x1b[34;06m"

colors["green"]="\x1b[32;01m"
colors["darkgreen"]="\x1b[32;06m"

colors["yellow"]="\x1b[33;01m"
colors["brown"]="\x1b[33;06m"

colors["red"]="\x1b[31;01m"
colors["darkred"]="\x1b[31;06m"

levels = {	"good" : colors["green"],
				"warn" : colors["yellow"],
				"bad"  : colors["red"]}

def nocolor():
	"turn off colorization"
	for x in colors.keys():
		colors[x]=""
	for x in levels.keys():
		levels[x]=""

def haveColors():
	return colors["reset"] != ""

def resetColor():
	return colors["reset"]

def bold(text):
	return colors["bold"]+text+colors["reset"]
def white(text):
	return bold(text)
def teal(text):
	return colors["teal"]+text+colors["reset"]
def turquoise(text):
	return colors["turquoise"]+text+colors["reset"]
def darkteal(text):
	return turquoise(text)
def fuscia(text):
	return colors["fuscia"]+text+colors["reset"]
def purple(text):
	return colors["purple"]+text+colors["reset"]
def blue(text):
	return colors["blue"]+text+colors["reset"]
def darkblue(text):
	return colors["darkblue"]+text+colors["reset"]
def green(text):
	return colors["green"]+text+colors["reset"]
def darkgreen(text):
	return colors["darkgreen"]+text+colors["reset"]
def yellow(text):
	return colors["yellow"]+text+colors["reset"]
def brown(text):
	return colors["brown"]+text+colors["reset"]
def darkyellow(text):
	return brown(text)
def red(text):
	return colors["red"]+text+colors["reset"]
def darkred(text):
	return colors["darkred"]+text+colors["reset"]
def good(text):
	return levels["good"]+text+colors["reset"]
def warn(text):
	return levels["warn"]+text+colors["reset"]
def bad(text):
	return levels["bad"]+text+colors["reset"]

class Output:
	def __init__(self,title='',max=100.0):
		self.max = max
		self.progress = 0.0
		self.eta = 0
		self.title = title
		self.aborting = False
		self.totalerrors = 0

	def setMax(self,max):
		self.max = max

	def setProgress(self,progress=None):
		"""
	Use this method to set
	the value of the progress bar
		"""
		self.progress = (100.0/self.max*float(progress))

	def abort(self):
		self.aborting = True
		self.update()

	def update(self):
		""" Use this method to update the progress bar"""
		pass

class OutputText(Output):
	def __init__(self,title = '', max=100.0,verbose=True,outstream=sys.stderr):
		Output.__init__(self,title,max)
		self.lastOut = None
		self.verbose = verbose
		self.outstream = outstream
		self.outstreamorig = outstream
		if (not sys.stdout.isatty()):
			nocolor()
		self.errstatus = None
		self.errornumber = 0
		self.errmsg = None
		self._max_width = None
        
	def setOutput(self, stream):
		self.outstream = stream

	def setVerbose(self, verbose):
		"""Sets verbosity. Input boolean."""
		self.verbose = verbose
		if verbose:
			self.outstream = self.outstreamorig
		else:
			self.outstream = file('/dev/null','w')

	def error(self, msg, countme=True):
		"""Print error message"""
		if countme:
			self.totalerrors = self.totalerrors + 1
		val = " " + bad("*") + " " + bold(msg)
		if self.outstream == sys.stdout:
			print >> sys.stderr, val
		else:
			print >> self.outstream, val
		return val

	def begin(self, msg):
		self.progress = 0
		self.errornumber = 0
		self.aborting = False
		self.errstatus = None
		self.errmsg = None
		self.title = msg
		self.update()
        
	def end(self, errno=0, errmsg=None):
		"""Ends a process"""
		self.aborting = True
		self.errstatus = self._end(errno,errmsg)
		self.errmsg = errmsg
		self.errornumber = errno
		self.update()

	def _end(self, errno=0, errmsg=None):
		"""Ends a process"""
		if errno == 0:
			val = '  ' + blue("[") + good(" OK ") +  blue("]")
		else:
			self.totalerrors = self.totalerrors + 1
			val = '  ' + blue("[") + bad(" !! ") +  blue("]")
		return val

	def getErrors(self):
		"""Return total number of errors"""
		return self.totalerrors

	def summary(self):
		"""Prints total number of errors"""
		val = "Total number of errors: " + str(self.totalerrors)
		if self.totalerrors > 0:
			print >> self.outstream, val
		return val
        
	def update(self):
		maxWidth = self._getMaxWidth()
		rubble = 15 + 8
		width = rubble + len(self.title)
		bar = '='*int(((maxWidth-width)*(self.progress/100)))
		if self.progress == 0:
			pattern = '%' + '-%d.%ds' % (len(self.title),len(self.title)) + '...       %' + '-%d.%ds ' % (maxWidth-width,maxWidth-width)
			out = pattern % (self.title,'')
		else:
			pattern = '%' + '-%d.%ds' % (len(self.title),len(self.title)) + '... %3i%% |%' + '-%d.%ds|' % (maxWidth-width,maxWidth-width)
			out = pattern % (self.title,int(self.progress),bar)
		if self.aborting:
			if self.progress < 100 and not self.errornumber == 0:
				out = '\r ' + bad("*") + " "+ out
			else:
				out = '\r ' + good("*") + " "+ out
			out = out + self.errstatus + '\n'
		else:
			out = '\r ' + warn("*") + " "+ bold(out)

		if out != self.lastOut: print >> self.outstream, out,
		self.lastOut = out
		if self.errmsg != None and self.errornumber != 0:
			self.error(self.errmsg, False)

	def _getMaxWidth(self):
		##if self._max_width != None: return self._max_width
		lines = os.popen("stty size 2>/dev/null").readlines()
		if lines == []:
			return 80
		else:
			return int(lines[0].split()[1])

def main():
	parser = optparse.OptionParser(usage="usage: %prog [options] dst",version="%%prog %s" % VERSION)
	parser.add_option("-v","--verbose",action="store_true",default=False,help="Enables more verbose output during backup")
	parser.add_option("-s","--source",metavar="DIR",help="User DIR as source for the backup process. Default is to use the current directory",default="./")
	parser.add_option("--verify",action="store_true",default=False,help="Verify that files are copied. This could slow down the backup considerably")
	parser.add_option("-i","--images",action="store_true",default=False,help="Only backup image files [jpg,jpeg,cr2,tif,tiff]")
	parser.add_option("-c","--clean",action="store_true",default=False,help="Removes all files stored on external media")
	parser.add_option("--statistics",action="store_true",default=False,help="Prints some statistics for the specified backup set")

	ext_group = optparse.OptionGroup(parser,"Extenal Media Options","These options are used when storing backup sets to external media")
	ext_group.add_option("-b","--burn",action="store_true",default=False,help="Burns backup set to external media")
	ext_group.add_option("-r","--range",default="all",help="Select range of files to be backed up. Format of RANGE is 'from-to', where 'from' and 'to' is of the following pattern: 'YYYY:MM:DD[HH:MM]'")
	ext_group.add_option("-t","--target",default=None,help="Copies files to be burnt to TARGET")
	ext_group.add_option("--iso",action="store_true",default=False,help="Create ISO file. Unless -t is used, the ISO file is placed in the current directory")
	parser.add_option_group(ext_group)
	
	adv_group = optparse.OptionGroup(parser,"Advanced Options", "")
	adv_group.add_option("--backup-info-file",default="backup.info",metavar="NAME",help="Use NAME as backup info file. Default is [backup.info]")
	adv_group.add_option("--only-hash",action="store_true",default=False,help="Dont do backup of identical files with differing file namse")
	adv_group.add_option("--dry-run",action="store_true",default=False,help="Dont do the actual copying")
	adv_group.add_option("--update",action="callback",callback=update,help="Check the internet for updates to this program")
	adv_group.add_option("--no-thumbnails",action="store_false",default=True,dest="thumbnails",help="Don't store thumbnails")
	adv_group.add_option("--thumbnail-directory",default="Thumbnails",metavar="DIR",help="Specify thumbnail directory DIR. Default is [Thumbnails]")
	adv_group.add_option("--create-thumbnails",action="store_true",default=False,help="Creates thumbnails for existing backup set")
	adv_group.add_option("--lookup",action="store_true",default=False,help="If specified all arguments specified at the end of the command line is threated as lookup targets")
	parser.add_option_group(adv_group)
	
	### Dangerous options
	group = optparse.OptionGroup(parser,"Dangerous Options","Caution: use these options at yout own risk.")
	group.add_option("--clean-destination",action="store_true",default=False,help="Cleans everything in the destination directory")
	group.add_option("--undo",action="store_true",default=False,help="Undo last change to backup info file")
	##group.add_option("--force-update",action="callback",callback=forceUpdate,help="Force update even if hash values doesn't match")
	parser.add_option_group(group)
	
	(options,args) = parser.parse_args(sys.argv[1:])
	if len(args) < 1:
		print parser.get_usage()
	else:
		if options.range != "all":
			if not RANGE.match(options.range):
				print >> sys.stderr, bad("Range has syntax errors")
				sys.exit(1)
		options.destination = args[0]
		backup = Backup(options)
	
if __name__ == "__main__": main()
