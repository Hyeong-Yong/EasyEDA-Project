const ids=JSON.parse(__taskArgs[0]||'[]');if(!Array.isArray(ids)||ids.length>20)throw new Error('Scoped list required');
return await Promise.all(ids.map(async uuid=>({uuid,model:await eda.lib_3DModel.get(uuid)})));
