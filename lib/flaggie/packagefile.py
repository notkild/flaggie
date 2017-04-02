#!/usr/bin/python
# vim:fileencoding=utf-8:noet
# (C) 2017 Michał Górny <gentoo@mgorny.alt.pl>
# Released under the terms of the 2-clause BSD license.

import codecs
import os
import os.path
import re
import shutil
import tempfile

from portage import VERSION as portage_ver
from portage.versions import vercmp


# comments start with '#' following whitespace
comment_regexp = re.compile(r'\s#.*$')


class PackageFileSet(object):
	class PackageFile(list):
		class PackageEntry(object):
			class InvalidPackageEntry(Exception):
				pass

			class PackageFlag(object):
				def __init__(self, s):
					if s[0] in ('-', '+'):
						self._modifier = s[0]
						self.name = s[1:]
					else:
						self._modifier = ''
						self.name = s

				@property
				def modifier(self):
					return self._modifier

				@modifier.setter
				def modifier(self, val):
					self._modifier = val

				def __lt__(self, other):
					return self.name < other.name

				def toString(self):
					return '%s%s' % (self.modifier, self.name)

			def __init__(self, l, whitespace=[]):
				sl = l.split()
				if not sl or sl[0].startswith('#'):  # whitespace
					raise self.InvalidPackageEntry()

				self.whitespace = whitespace
				self.as_str = l
				self.modified = False
				self.package = sl.pop(0)
				self.flags = []

				for x in sl:
					if x.startswith('#'):
						break
					self.flags.append(self.PackageFlag(x))

				m = comment_regexp.search(l)
				if m:
					self.trailing_whitespace = m.group(0) + '\n'
				else:
					self.trailing_whitespace = '\n'

			def toString(self):
				ret = ''.join(self.whitespace)
				if not self.modified:
					ret += self.as_str
				else:
					ret += '%s %s%s' % (self.package,
						' '.join(x.toString() for x in self.flags),
						self.trailing_whitespace)
				return ret

			def append(self, flag):
				if not isinstance(flag, self.PackageFlag):
					flag = self.PackageFlag(flag)
				self.flags.append(flag)
				self.modified = True
				return flag

			def remove(self, flag):
				self.flags.remove(flag)
				self.modified = True

			def sort(self):
				newflags = sorted(self.flags)
				if newflags != self.flags:
					self.flags = newflags
					self.modified = True

			def __lt__(self, other):
				return self.package < other.package

			def __iter__(self):
				""" Iterate over all flags in the entry. """
				for f in reversed(self.flags):
					yield f

			def __len__(self):
				return len(self.flags)

			def __getitem__(self, flag):
				""" Iterate over occurences of flag in the entry,
					returning them in the order of occurence. """
				for f in self:
					if flag == f.name:
						yield f

			def __delitem__(self, flag):
				""" Remove all occurences of a flag. """
				flags = []
				for f in self:
					if flag == f.name:
						flags.append(f)
				for f in flags:
					self.remove(f)

		def __init__(self, path):
			list.__init__(self)
			self.path = path
			# _modified is for when items are removed
			self._modified = False
			if not os.path.exists(path):
				self.trailing_whitespace = []
				return
			f = codecs.open(path, 'r', 'utf8')

			ws = []
			for l in f:
				try:
					e = self.PackageEntry(l, ws)
					ws = []
				except self.PackageEntry.InvalidPackageEntry:
					ws.append(l)
				else:
					self.append(e)

			self.trailing_whitespace = ws
			f.close()

		def sort(self):
			newlist = sorted(self)
			if newlist != self:
				self[:] = newlist
				self.modified = True

		@property
		def modified(self):
			if self._modified:
				return True
			for e in self:
				if e.modified:
					return True
			return False

		@modified.setter
		def modified(self, val):
			self._modified = val

		@property
		def data(self):
			data = ''
			for l in self:
				if not l.modified or l:
					data += l.toString()
			data += ''.join(self.trailing_whitespace)
			return data

		def write(self):
			if not self.modified:
				return

			data = self.data

			backup = self.path + '~'
			if not data:
				try:
					shutil.move(self.path, backup)
				except IOError:
					os.unlink(self.path)
			else:
				if not os.path.isdir(os.path.dirname(self.path)):
					try:
						os.makedirs(os.path.dirname(self.path))
					except Exception:
						pass
				f = tempfile.NamedTemporaryFile('wb', delete=False,
						dir=os.path.dirname(os.path.realpath(self.path)))

				tmpname = f.name

				try:
					f = codecs.getwriter('utf8')(f)
					f.write(data)
					f.close()

					try:
						shutil.copy2(self.path, backup)
					except IOError:
						backup = None
					shutil.move(tmpname, self.path)
				except Exception:
					os.unlink(tmpname)
					raise

				if backup is not None:
					shutil.copymode(backup, self.path)
				else:
					umask = os.umask(0o22)
					os.umask(umask)
					os.chmod(self.path, 0o666 & ~umask)

			for e in self:
				e.modified = False
			self.modified = False

	def __init__(self, path):
		if not isinstance(path, tuple) and not isinstance(path, list):
			path = (path,)

		self._paths = path
		self._files = []

	@property
	def files(self):
		if not self._files:
			self.read()
		return self._files

	def migrate(self):
		paths = self._paths
		if len(paths) <= 1:
			return

		lp = paths[-1]
		for f in self.files:
			if f.path == lp or os.path.dirname(f.path) == lp:
				lf = f
				break
		else:
			raise AssertionError('Final file not found while trying to migrate.')

		for p in paths[:-1]:
			for f in self.files:
				if f.path == p or os.path.dirname(f.path) == p:
					lf[0:0] = f
					del f[:]
					f.modified = True

		lf.modified = True

	def read(self):
		if self._files:
			return

		for fn in self._paths:
			if os.path.isdir(fn):
				files = []
				for toppath, wdirs, wfiles in os.walk(fn):
					for f in wfiles:
						if f.startswith('.') or f.endswith('~'):
							continue
						files.append(os.path.join(toppath, f))

				if not files:
					files = [os.path.join(fn, 'flaggie')]
				else:
					files.sort()
			else:
				files = [fn]

			for path in files:
				self._files.append(self.PackageFile(path))

	def write(self):
		if not self._files:
			return

		for f in self._files:
			f.write()
			del f
		self._files = []

	def append(self, pkg):
		f = self.files[-1]
		if not isinstance(pkg, f.PackageEntry):
			pkg = f.PackageEntry(pkg)
		pkg.modified = True
		f.append(pkg)
		return pkg

	def remove(self, pkg):
		found = False
		for f in self.files:
			try:
				f.remove(pkg)
			except ValueError:
				pass
			else:
				f.modified = True
				found = True
		if not found:
			raise ValueError('%s not found in package.* files.' % pkg)

	def sort(self):
		for f in self.files:
			f.sort()

	def __iter__(self):
		""" Iterate over package entries. """
		for f in reversed(self.files):
			for e in reversed(f):
				yield e

	def __getitem__(self, pkg):
		""" Get package entries for a package in order of effectiveness
			(the last declarations in the file are effective, and those
			will be returned first).

			If pkg is None and PackageFileSet has self.makeconfvar set,
			calling self[None] will return the MakeConfVariable instance.
		"""

		if pkg is None:
			if self.makeconfvar is not None:
				for e in self.makeconfvar:
					yield e
			else:
				raise KeyError(
					'PackageFileSet[None] requested but no MakeConfVariable assigned.')
			return

		for e in self:
			if pkg == e.package:
				yield e

	def __delitem__(self, pkg):
		""" Delete all package entries for a package. """
		for f in self.files:
			entries = []
			for e in f:
				if pkg == e.package:
					entries.append(e)
			for e in entries:
				f.remove(e)
			f.modified = True

	makeconfvar = None


class PackageKeywordsFileSet(PackageFileSet):
	def __init__(self, path, dbapi):
		PackageFileSet.__init__(self, path)

		self._defkw = frozenset('~' + x for x
			in dbapi.settings['ACCEPT_KEYWORDS'].split()
			if x[0] not in ('~', '-'))

	def read(self, *args):
		if self._files:
			return

		PackageFileSet.read(*((self,) + args))

		# set defaults
		for e in self:
			if not e:
				for f in self._defkw:
					e.append(f)
				e.modified = False

	def write(self, *args):
		if not self._files:
			return

		for f in self.files:
			for e in f:
				if e.modified and set(x.toString() for x in e.flags) == self._defkw:
					# Yeah, that's what it looks like -- a workaround.
					e.as_str = e.package + '\n'
					e.modified = False
					f.modified = True

		PackageFileSet.write(*((self,) + args))


class PackageEnvFileSet(PackageFileSet):
	def write(self, *args):
		if not self._files:
			return

		for f in self.files:
			for e in f:
				if e.modified:
					rlist = [fl for fl in e if fl.modifier == '-']
					for fl in rlist:
						e.remove(fl)

		PackageFileSet.write(*((self,) + args))


class PackageFiles(object):
	def __init__(self, basedir, dbapi, mkconf=None):
		def p(x):
			return os.path.join(basedir, x)

		pkw = [p('package.keywords')]
		if vercmp(portage_ver, '2.1.9') >= 0:
			pkw.append(p('package.accept_keywords'))

		self.files = {
			'use': PackageFileSet(p('package.use')),
			'kw': PackageKeywordsFileSet(pkw, dbapi),
			'lic': PackageFileSet(p('package.license')),
			'env': PackageEnvFileSet(p('package.env'))
		}

		if mkconf:
			for k, f in self.files.items():
				f.makeconfvar = mkconf[k]

	def __getitem__(self, k):
		return self.files[k]

	def __iter__(self):
		return iter(self.files.values())

	def write(self):
		for f in self:
			f.write()
