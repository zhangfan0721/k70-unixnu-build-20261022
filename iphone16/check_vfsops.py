"""Check the official helper body, API export and its lookup contract."""
import hashlib
import re
import subprocess


def check(source, overlay, out, deployment):
    text = (overlay / 'bsd/vfs/vfs_subr.c').read_text()
    body = re.search(r'struct mount \*\nvfs_getvfs_with_vfsops\(.*?\n\}', text, re.S)[0]
    # Exactly the official xnu-10063.141.1 implementation, not an alias/stub.
    expected = '''struct mount *
vfs_getvfs_with_vfsops(fsid_t *fsid, const struct vfsops * const ops)
{
	mount_t mp = mount_list_lookupby_fsid(fsid, 0, 0);

	if (mp != NULL && mp->mnt_op != ops) {
		mp = NULL;
	}
	return mp;
}'''
    if body != expected:
        raise ValueError('VFS helper differs from the reviewed upstream body')
    if '_vfs_getvfs_with_vfsops\n' not in (overlay / 'config/BSDKernel.exports').read_text():
        raise ValueError('Missing real BSD interface export')
    if 'mount_t vfs_getvfs_with_vfsops(fsid_t *fsid, const struct vfsops *ops);' not in (overlay / 'bsd/sys/mount.h').read_text():
        raise ValueError('Missing official declaration')
    # The restored ABI header must be the original fixed XNU22 header.
    header = overlay / 'iokit/IOKit/IORPC.h'
    original = source / 'iokit/IOKit/IORPC.h'
    if header.exists() and header.read_bytes() != original.read_bytes():
        raise ValueError('IORPC layout still modified')
    path = out / 'vfsops-contract.c'
    path.write_text('''#define NULL ((void *)0)
typedef struct { int val[2]; } fsid_t;
struct vfsops { int identity; };
struct mount { const struct vfsops *mnt_op; };
typedef struct mount *mount_t;
static mount_t selected;
static fsid_t *last_fsid;
static int last_locked, last_withref;
static mount_t mount_list_lookupby_fsid(fsid_t *id, int locked, int withref) {
 last_fsid = id; last_locked = locked; last_withref = withref;
 return selected;
}
''' + body + '''
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
int main(void) {
 fsid_t id = {{1,2}};
 const struct vfsops a = {1}, b = {2};
 struct mount m = {&a};
 selected = NULL;
 CHECK(vfs_getvfs_with_vfsops(&id, &a) == NULL);
 selected = &m;
 CHECK(vfs_getvfs_with_vfsops(&id, &a) == &m);
 CHECK(vfs_getvfs_with_vfsops(&id, &b) == NULL);
 CHECK(last_fsid == &id && last_locked == 0 && last_withref == 0);
 CHECK(m.mnt_op == &a);
 return 0;
}
''')
    executable, obj = out / 'vfsops-contract', out / 'vfsops-ios16.o'
    subprocess.run(['clang', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(executable)], check=True)
    subprocess.run([str(executable.resolve())], check=True)
    subprocess.run(['clang', '--target=arm64-apple-ios16.0', '-ffreestanding',
        '-Wall', '-Wextra', '-Werror', '-c', str(path), '-o', str(obj)], check=True)
    deployment(obj)
    return {'official_body_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'lookup_cases_and_ios16_object_checked': True, 'real_mount_lifetime_runtime_tested': False}
