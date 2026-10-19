const key=__taskArgs[0];if(!key||key.length>100)throw new Error('Search key required');
return await eda.lib_3DModel.search(key,undefined,undefined,20,1);
