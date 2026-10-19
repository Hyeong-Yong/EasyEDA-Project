const project = await eda.dmt_Project.getCurrentProjectInfo();
const document = await eda.dmt_SelectControl.getCurrentDocumentInfo();
const projectLibraryUuid = await eda.lib_LibrariesList.getProjectLibraryUuid();
const systemLibraryUuid = await eda.lib_LibrariesList.getSystemLibraryUuid();
return {project,document,projectLibraryUuid,systemLibraryUuid};
