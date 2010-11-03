#!/usr/bin/python
#	vim:fileencoding=utf-8
# (C) 2010 Michał Górny <gentoo@mgorny.alt.pl>
# Released under the terms of the 3-clause BSD license.

import codecs, glob, sys, os.path
from optparse import OptionParser
import portage
from portage.dbapi.dep_expand import dep_expand

from flaggie import PV

def print_help(option, arg, val, parser):
	class PseudoOption:
		def __init__(self, opt, help):
			parser.formatter.option_strings[self] = opt
			self.help = help
			self.dest = ''

	parser.print_help()
	print('''
Actions:''')

	actions = [
		('+flag', 'explicitly enable flag'),
		('-flag', 'explicitly disable flag'),
		('%flag', 'reset flag to the default state (remove it completely)'),
		('%', 'reset all package flags to the default state (drop the package from package.use)'),
		('?flag', 'print the status of a particular flag'),
		('?', 'print package flags')
	]

	parser.formatter.indent()
	for a,b in actions:
		sys.stdout.write(parser.formatter.format_option(PseudoOption(a, b)))
	parser.formatter.dedent()
	sys.exit(0)

class ParserError(Exception):
	pass

class PackageFileSet:
	class PackageFile(list):
		class Whitespace(object):
			def __init__(self, l):
				self.data = l

			def toString(self):
				return self.data

			@property
			def modified(self):
				return False

			@modified.setter
			def modified(self, newval):
				pass

		class PackageEntry:
			class InvalidPackageEntry(Exception):
				pass

			class PackageFlag:
				def __init__(self, s):
					if s[0] in ('-', '+'):
						self.modifier = s[0]
						self.name = s[1:]
					else:
						self.modifier = ''
						self.name = s

				def toString(self):
					return '%s%s' % (self.modifier, self.name)

			def __init__(self, l):
				sl = l.split()
				if not sl or sl[0].startswith('#'): # whitespace
					raise self.InvalidPackageEntry()

				self.as_str = l
				self.modified = False
				self.package = sl.pop(0)
				self.flags = [self.PackageFlag(x) for x in sl]

			def toString(self):
				if not self.modified:
					return self.as_str
				else:
					return ' '.join([self.package] + \
							[x.toString() for x in self.flags]) + '\n'

			def append(self, flag):
				if not isinstance(flag, self.PackageFlag):
					flag = self.PackageFlag(flag)
				self.flags.append(flag)
				self.modified = True
				return flag

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
					if f.name == flag:
						yield f

			def __delitem__(self, flag):
				""" Remove all occurences of a flag. """
				flags = []
				for f in self.flags:
					if f.name == flag:
						flags.append(f)
				for f in flags:
					self.flags.remove(f)

				self.modified = True

		def __init__(self, path):
			self.path = path
			# _modified is for when items are removed
			self._modified = False
			f = codecs.open(path, 'r', 'utf8')
			for l in f:
				try:
					e = self.PackageEntry(l)
				except self.PackageEntry.InvalidPackageEntry:
					e = self.Whitespace(l)
				self.append(e)
			f.close()

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

		def write(self):
			if not self.modified:
				return

			f = codecs.open(self.path, 'w', 'utf8')
			for l in self:
				f.write(l.toString())
			f.close()

			for e in self:
				e.modified = False
			self.modified = False

	def __init__(self, path):
		self.files = []
		if os.path.isdir(path):
			files = sorted(glob.glob(os.path.join(path, '*')))
		else:
			files = [path]

		for path in files:
			self.files.append(self.PackageFile(path))

	def write(self):
		for f in self.files:
			f.write()

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

	def __iter__(self):
		""" Iterate over package entries. """
		for f in reversed(self.files):
			for e in reversed(f):
				if isinstance(e, f.PackageEntry):
					yield e

	def __getitem__(self, pkg):
		""" Get package entries for a package in order of effectiveness
			(the last declarations in the file are effective, and those
			will be returned first). """
		for e in self:
			if e.package == pkg:
				yield e

	def __delitem__(self, pkg):
		""" Delete all package entries for a package. """
		for f in self.files:
			entries = []
			for e in f:
				if e.package == pkg:
					entries.append(e)
			for e in entries:
				f.remove(e)
			f.modified = True

class Caches(object):
	class DBAPICache(object):
		aux_key = None

		def __init__(self, dbapi):
			if not self.aux_key:
				raise AssertionError('DBAPICache.aux_key needs to be overriden.')
			self.dbapi = dbapi
			self.cache = {}

		@property
		def glob(self):
			raise AssertionError('DBAPICache.glob() needs to be overriden.')

		def _aux_clean(self, arg):
			return arg

		def __getitem__(self, k):
			if k not in self.cache:
				flags = set()
				# get widest match possible to make sure we do not complain without a reason
				for p in self.dbapi.xmatch('match-all', k):
					flags |= set([self._aux_clean(x) for x in \
							self.dbapi.aux_get(p, (self.aux_key,))[0].split()])
				self.cache[k] = flags
			return self.cache[k]

	class FlagCache(DBAPICache):
		aux_key = 'IUSE'

		@property
		def glob(self):
			if None not in self.cache:
				flags = set()
				for r in self.dbapi.porttrees:
					try:
						f = open(os.path.join(r, 'profiles', 'use.desc'), 'r')
					except IOError:
						pass
					else:
						for l in f:
							ll = l.split(' - ', 1)
							if len(ll) > 1:
								flags.add(ll[0])
						f.close()
				self.cache[None] = flags

			return self.cache[None]

		def _aux_clean(self, arg):
			return arg.lstrip('+-')

	class KeywordCache(DBAPICache):
		aux_key = 'KEYWORDS'

		@property
		def glob(self):
			if None not in self.cache:
				kws = set()
				for r in self.dbapi.porttrees:
					try:
						f = open(os.path.join(r, 'profiles', 'arch.list'), 'r')
					except IOError:
						pass
					else:
						for l in f:
							if l.strip() and not l.startswith('#'):
								kws.add(l.strip())
						f.close()

				# testing keywords
				for k in kws.copy():
					kws.add('~%s' % k)
				# and the ** special keyword
				kws.add('**')
				self.cache[None] = kws

			return self.cache[None]

		def __getitem__(self, k):
			ret = Caches.DBAPICache.__getitem__(self, k)
			ret.add('**')
			return ret

	def __init__(self, dbapi):
		self.flags = self.FlagCache(dbapi)
		self.keywords = self.KeywordCache(dbapi)

	def glob_whatis(self, arg, restrict = None):
		if not restrict:
			restrict = ('use', 'kw')
		ret = set()
		if 'use' in restrict and arg in self.flags.glob:
			ret.add('use')
		if 'kw' in restrict and arg in self.keywords.glob:
			ret.add('kw')
		return ret

	def whatis(self, arg, pkg, restrict = None):
		if not restrict:
			restrict = ('use', 'kw')
		ret = set()
		if 'use' in restrict and arg in self.flags[pkg]:
			ret.add('use')
		if 'kw' in restrict and arg in self.keywords[pkg]:
			ret.add('kw')
		return ret

	def describe(self, ns):
		if ns == 'use':
			return 'flag'
		elif ns == 'kw':
			return 'keyword'
		else:
			raise AssertionError('Unexpected ns %s' % ns)

class Action(object):
	class _argopt(object):
		def __init__(self, arg, key):
			self.args = set((arg,))
			self.ns = None

		def clarify(self, pkgs, cache):
			if len(self.args) > 1:
				raise AssertionError('clarify() needs to be called before actions are joined.')
			arg = self.args.pop()
			if not arg:
				self.args.add(arg)
				return

			splitarg = arg.split('::', 1)
			if len(splitarg) > 1:
				ns = set((splitarg[0],))
				arg = splitarg[1]
			else:
				ns = None

			if not pkgs:
				wis = cache.glob_whatis(arg, restrict = ns)
				if len(wis) > 1:
					raise ParserError('Ambiguous argument: %s (matches %s).' % \
							(arg, ', '.join(wis)))
				elif wis:
					ns = wis.pop()
				elif ns:
					ns = ns.pop()
					print('Warning: %s seems to be an incorrect global %s' % \
							(arg, cache.describe(ns)))
				else:
					ns = 'use'
					print('Warning: %s seems to be an incorrect global flag' % arg)
			else:
				for p in pkgs:
					wis = cache.whatis(arg, p, restrict = ns)
					if wis:
						gwis = wis
					elif ns:
						gwis = ns
					else:
						gwis = cache.glob_whatis(arg)

					if len(gwis) > 1:
						raise ParserError('Ambiguous argument: %s (matches %s).' % \
								(arg, ', '.join(wis)))
					elif wis:
						ns = wis.pop()
					else:
						if gwis:
							ns = gwis.pop()
							print('Warning: %s seems to be an incorrect %s for %s' % \
									(arg, cache.describe(ns), p))
						else:
							ns = 'use'
							print('Warning: %s seems to be an incorrect flag for %s' % (arg, p))
			self.ns = ns
			self.args.add(arg)

		def append(self, arg):
			if isinstance(arg, self.__class__):
				self.args.update(arg.args)
			else:
				self.args.add(arg)

	class _argreq(_argopt):
		def __init__(self, arg, key, *args, **kwargs):
			if not arg:
				raise ParserError('%s action requires an argument!' % key)

			newargs = (self, arg, key) + args
			Action._argopt.__init__(*newargs, **kwargs)

	class EffectiveEntryOp(object):
		def grab_effective_entry(self, p, arg, f, rw = False):
			entries = f[p]
			for pe in entries:
				flags = pe[arg]
				for f in flags:
					if rw:
						pe.modified = True
					return f
			else:
				if not rw:
					return None
				# No matching flag found. Try to append to the last
				# package entry if there's one. Otherwise, append
				# a new entry.
				for pe in entries:
					return pe.append(arg)
				else:
					return f.append(p).append(arg)

	class enable(_argreq, EffectiveEntryOp):
		def __call__(self, pkgs, puse):
			for p in pkgs:
				for arg in self.args:
					f = self.grab_effective_entry(p, arg, puse, rw = True)
					f.modifier = ''

	class disable(_argreq, EffectiveEntryOp):
		def __call__(self, pkgs, puse):
			for p in pkgs:
				for arg in self.args:
					f = self.grab_effective_entry(p, arg, puse, rw = True)
					f.modifier = '-'

	class reset(_argopt):
		def __call__(self, pkgs, puse):
			for p in pkgs:
				if '' in self.args:
					del puse[p]
				else:
					for pe in puse[p]:
						for f in self.args:
							del pe[f]
						if not pe:
							puse.remove(pe)

	class output(_argopt, EffectiveEntryOp):
		def __call__(self, pkgs, puse):
			for p in pkgs:
				l = [p]
				if '' in self.args:
					flags = {}
					for pe in puse[p]:
						for f in pe:
							if f.name not in flags:
								flags[f.name] = f
					for fn in sorted(flags):
						l.append(flags[fn].toString())
				else:
					for arg in sorted(self.args):
						f = self.grab_effective_entry(p, arg, puse)
						l.append(f.toString() if f else '?%s' % arg)

				print(' '.join(l))

	mapping = {
		'+': enable,
		'-': disable,
		'%': reset,
		'?': output
	}

	class NotAnAction(Exception):
		pass

	def __new__(cls, *args, **kwargs):
		a = args[0]
		if a[0] in cls.mapping:
			newargs = (a[1:], a[0]) + args[1:]
			return cls.mapping[a[0]](*newargs, **kwargs)
		else:
			raise cls.NotAnAction

def get_dbapi():
	ptrees = portage.create_trees()
	# XXX: support ${ROOT}
	dbapi = ptrees['/']['porttree'].dbapi

	return dbapi

class ActionSet(list):
	def __init__(self, cache = None):
		list.__init__(self)
		self._cache = cache
		self.pkgs = []

	def append(self, item):
		if isinstance(item, Action._argopt):
			item.clarify(self.pkgs, self._cache)
			for a in self:
				if isinstance(item, a.__class__) and item.ns == a.ns:
					a.append(item)
					break
			else:
				list.append(self, item)
				self.sort(key = lambda x: Action.mapping.values().index(x.__class__))
		elif isinstance(item, basestring):
			self.pkgs.append(item)
		else:
			raise ValueError('Incorrect type passed to ActionSet.append()')

	def __call__(self, puse, pkw):
		if self.pkgs:
			for a in self:
				if a.ns == 'use':
					f = puse
				elif a.ns == 'kw':
					f = pkw
				else:
					raise AssertionError('Unexpected ns %s in ActionSet.__call__()' % a.ns)
				a(self.pkgs, f)
		else:
			raise NotImplementedError('Global actions are not supported yet')

def parse_actions(args, dbapi):
	out = []
	cache = Caches(dbapi)
	actset = ActionSet(cache = cache)

	for i, a in enumerate(args):
		if not a:
			continue
		try:
			try:
				a = Action(a)
			except Action.NotAnAction:
				if actset:
					out.append(actset)
					actset = ActionSet(cache = cache)
				try:
					atom = dep_expand(a, mydb = dbapi, settings = portage.settings)
				except portage.exception.AmbiguousPackageName as e:
					raise ParserError, 'ambiguous package name, matching: %s' % e
				if atom.startswith('null/'):
					raise ParserError, 'unable to determine the category (mistyped name?)'
				actset.append(atom)
			else:
				actset.append(a)
		except ParserError as e:
			raise ParserError, 'At argv[%d]=\'%s\': %s' % (i, a, e)

	if actset:
		out.append(actset)
	return out

def main(argv):
	opt = OptionParser(
			usage='%prog [options] [<global-use-actions>] [<package> <actions>] [...]',
			version='%%prog %s' % PV,
			description='Easily manipulate USE flags in make.conf and package.use.',
			add_help_option=False
	)
	opt.disable_interspersed_args()
	opt.add_option('-h', '--help', action='callback', callback=print_help,
			help = 'print help message and exit')
	(opts, args) = opt.parse_args(argv[1:])

	dbapi = get_dbapi()
	try:
		act = parse_actions(args, dbapi)
	except ParserError as e:
		print(e)
		return 1

	if not act:
		print_help(None, '', '', opt)

	# (only for testing, to be replaced by something more optimal)
	puse = PackageFileSet('/etc/portage/package.use')
	pkw = PackageFileSet('/etc/portage/package.keywords')

	for actset in act:
		actset(puse, pkw)

	pkw.write()
	puse.write()

	return 0

if __name__ == '__main__':
	sys.exit(main(sys.argv))
