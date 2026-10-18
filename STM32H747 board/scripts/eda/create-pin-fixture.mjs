const lib = await eda.lib_LibrariesList.getProjectLibraryUuid();
if (lib !== 'project') throw new Error('Refusing non-project library write');
const ELIB_SymbolType = {COMPONENT:2};
const symbolUuid = await eda.lib_Symbol.create(lib,'STM32H747_RECONSTRUCTION_PIN_FIXTURE',[],ELIB_SymbolType.COMPONENT,'Reconstruction API format validation');
if (!symbolUuid) throw new Error('Symbol creation failed');
return {libraryUuid:lib,symbolUuid,source:await eda.lib_Symbol.getDocumentSource(symbolUuid,lib)};
