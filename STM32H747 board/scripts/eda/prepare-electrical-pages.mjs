const p = await eda.dmt_Project.getCurrentProjectInfo();
const schUuid = 'f761590e40a058a2';
const coverUuid = '6f4a7195e71d5772';
const allPages = await eda.dmt_Schematic.getAllSchematicPagesInfo();
if (allPages.some(x => x.parentSchematicUuid !== schUuid)) throw new Error('Unexpected schematic; refusing migration');
const backup = await eda.sys_FileManager.getProjectFileByProjectUuid(p.uuid, 'STM32H747_before_cover_removal_20261014', undefined, 'epro2');
if (!backup) throw new Error('Backup export failed');
const backupSaved = await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/checkpoints/STM32H747_before_cover_removal_20261014.epro2', backup, undefined, false);
if (!backupSaved) throw new Error('Backup write failed or backup already exists; no changes made');
const names = ['02_MCU', '03_MCU_POWER', '04_SDRAM', '05_ENET_USB_VCP', '06_ADC_TIMER_DAC'];
const created = [];
for (const name of names) {
  const uuid = await eda.dmt_Schematic.createSchematicPage(schUuid);
  if (!uuid) throw new Error('Page creation failed: ' + name);
  const renamed = await eda.dmt_Schematic.modifySchematicPageName(uuid, name);
  if (!renamed) throw new Error('Page rename failed: ' + uuid);
  created.push({uuid, name});
}
if (allPages.some(x => x.uuid === coverUuid)) {
  const removed = await eda.dmt_Schematic.deleteSchematicPage(coverUuid);
  if (!removed) throw new Error('Cover page deletion failed');
}
const pages = await eda.dmt_Schematic.getAllSchematicPagesInfo();
const sorted = names.map(name => pages.find(x => x.name.toUpperCase() === name));
if (sorted.some(x => !x) || pages.some(x => x.uuid === coverUuid)) throw new Error('Page migration verification failed');
if (!await eda.dmt_Schematic.reorderSchematicPages(schUuid, sorted)) throw new Error('Reorder failed');
await eda.dmt_EditorControl.openDocument(created[0].uuid);
return {backupSaved, backupBytes:backup.size, coverRemoved:true, pages:created};
