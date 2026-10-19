let paths,error;try{paths=await eda.sys_FileSystem.getLibrariesPaths();}catch(e){error=String(e);}
return {paths,error};
