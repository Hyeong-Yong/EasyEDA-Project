const all = await eda.dmt_Schematic.getAllSchematicsInfo();
return all.map(s=>({uuid:s.uuid,name:s.name,pages:s.page?.map(p=>({uuid:p.uuid,name:p.name}))}));
