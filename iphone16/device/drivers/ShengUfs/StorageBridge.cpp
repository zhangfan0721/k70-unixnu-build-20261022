// SPDX-License-Identifier: BSD-2-Clause-Patent
// Minimal IOBlockStorageDevice base-class bridge for the K70 native UFS path.
//
// Only the symbols this compilation unit needs are provided; the runtime
// semantics of the published media still come from the prelinked original
// IOStorageFamily.  Nothing here registers a second metaclass for the class:
// the definition below exists solely to satisfy the kernel link, and the
// prelinked component keeps ownership of the real instance machinery.
//
// Enabled only for the diagnostic full build:
//   -DK70_NATIVE_UFS_FULL_BLOCK=1

#include <IOKit/IOService.h>
#include <IOKit/storage/IOBlockStorageDevice.h>

#if K70_NATIVE_UFS_FULL_BLOCK

// The prelinked IOStorageFamily owns these; the bridge forwards to the same
// implementations when the component is present at runtime.

OSDefineMetaClassAndAbstractStructors(IOBlockStorageDevice, IOService)

bool IOBlockStorageDevice::init(OSDictionary *properties)
{
	return IOService::init(properties);
}

OSObject *IOBlockStorageDevice::getProperty(const OSSymbol *key) const
{
	return IOService::getProperty(key);
}

IOReturn IOBlockStorageDevice::setProperties(OSObject *properties)
{
	return IOService::setProperties(properties);
}

IOReturn IOBlockStorageDevice::requestIdle(void)
{
	return kIOReturnSuccess;
}

IOReturn IOBlockStorageDevice::doUnmap(IOBlockStorageDeviceExtent *,
					UInt32,
					IOStorageUnmapOptions)
{
	return kIOReturnUnsupported;
}

IOReturn IOBlockStorageDevice::doSetPriority(IOBlockStorageDeviceExtent *,
					     UInt32,
					     IOStoragePriority)
{
	return kIOReturnUnsupported;
}

IOReturn IOBlockStorageDevice::doGetProvisionStatus(UInt64,
						UInt64,
						UInt32 *,
						IOBlockStorageProvisionDeviceExtent *,
						IOStorageGetProvisionStatusOptions)
{
	return kIOReturnUnsupported;
}

IOReturn IOBlockStorageDevice::doSynchronize(UInt64,
					     UInt64,
					     IOStorageSynchronizeOptions)
{
	return kIOReturnUnsupported;
}

IOReturn IOBlockStorageDevice::doSynchronizeCache(void)
{
	return kIOReturnUnsupported;
}

IOReturn IOBlockStorageDevice::getWriteCacheState(bool *enabled)
{
	if (enabled) {
		*enabled = false;
	}
	return kIOReturnSuccess;
}

IOReturn IOBlockStorageDevice::setWriteCacheState(bool)
{
	return kIOReturnUnsupported;
}

#endif  // K70_NATIVE_UFS_FULL_BLOCK