const project = await eda.dmt_Project.getCurrentProjectInfo();
const expectedProjectUuid = '4d4671fe9a78f6b1578521c2dc6be53db20dc0cc6cb10fdfc81febaa87f5af94';
if (!project || project.uuid !== expectedProjectUuid || project.friendlyName !== 'STM32H747_MCU_BOARD_v19') throw new Error('STM32H747 project identity mismatch.');
const pages = await eda.dmt_Schematic.getAllSchematicPagesInfo();
const page = pages.find(item => item.name === '01_HIERARCHY');
if (!page) throw new Error('Page 1 was not found.');
const tabId = await eda.dmt_EditorControl.openDocument(page.uuid);
if (!tabId) throw new Error('Page 1 could not be opened.');
const source = await eda.sys_FileManager.getDocumentSource();
if (!source || !source.includes('01_HIERARCHY')) throw new Error('Native source identity mismatch.');
const counts = {};
for (const line of source.split('\n')) {
  if (!line.trim()) continue;
  const separator = line.indexOf('||');
  if (separator < 0) continue;
  const header = JSON.parse(line.slice(0, separator));
  counts[header.type] = (counts[header.type] || 0) + 1;
}
const saved = await eda.sch_Document.save();
if (!saved) throw new Error('Native schematic save failed.');
const drc = await eda.sch_Drc.check(true, false, true);
const svg = await eda.sch_ManufactureData.getSvgFile('STM32H747_page1_native');
if (!svg) throw new Error('Native SVG export failed.');
const exportPath = 'C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/page1/' + svg.name;
const exported = await eda.sys_FileSystem.saveFileToFileSystem(exportPath, svg, undefined, false);
if (!exported) throw new Error('Native SVG output could not be saved.');
const fitted = await eda.dmt_EditorControl.zoomToRegion(0, 1653.5, 1169.3, 0, tabId);
return {project, page, tabId, counts, saved, drc, exported, exportPath, exportFileName: svg.name, fitted};
