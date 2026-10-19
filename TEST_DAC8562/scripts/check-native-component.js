const libraryUuid=await eda.lib_LibrariesList.getProjectLibraryUuid();const device=await eda.lib_Device.get('39c4afae03c30d3f',libraryUuid);return {libraryUuid,device};
