const file=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/source-models/kicad/Capacitor_SMD.3dshapes/C_0402_1005Metric.step');
return file?{name:file.name,type:file.type,size:file.size,lastModified:file.lastModified,header:(await file.text()).slice(0,350)}:null;
