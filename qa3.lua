local function printf(fmt,...) print(string.format(fmt,...)) end
function QuickApp:onInit()
    quickApp = self
    self:debug("QA name",self.name,"id",self.id,"type",self.type)
    self:trace("Trace message")
    self:warning("Warning message")
    self:error("Error message") 
    self:debug("fibaro.config")
    for k,v in pairs(fibaro.config) do
        printf("   %s=%s",k,json.encode(v))
    end

    self:testGlobalVariables()
end

function QuickApp:testGlobalVariables()
    api.post("/globalVariables",{ name = "A42", value = "B" })
    local val,t = fibaro.getGlobalVariable("A42")
    printf("Global 'A42' = %s (%s)",val,os.date('%c',t))
    fibaro.setGlobalVariable("A42","C")
    val,t = fibaro.getGlobalVariable("A42")
    printf("Global 'A42' = %s (%s)",val,os.date('%c',t))
    api.delete("/globalVariables/A42")
end