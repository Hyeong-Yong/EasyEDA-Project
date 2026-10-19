const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const project=await eda.dmt_Project.getCurrentProjectInfo();
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/adc10-labtool-20261018/libraries/reverse-protection/STM32H747_labtool_reverse_protection_new_libraries_20261018.epro2');
if(!file)throw new Error('Protection-only bundle missing');
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))).map(v=>v.toString(16).padStart(2,'0')).join('');
if(hash!=='ebf18f61170a0ca837994cdf43f2c769fca2e497f85f784c259c970cd6662ea2')throw new Error('Protection bundle changed');
const imported=await eda.sys_FileManager.importProjectByProjectFile(file,'EasyEDA Pro',{importOption:'ImportDocument'},{operation:'Existing Project',existingProjectUuid:project.uuid});
if(!imported)throw new Error('Protection import failed/unknown; inspect, do not retry');
return{imported,packageSha256:hash,expectedNewDocuments:3,meaning:'Verify actual checkpoint before use'};
